import os
import sys
from datetime import datetime

import numpy as np
import pandas as pd
import pygsheets
import pytz
from dotenv import load_dotenv
from pytz import timezone
from shillelagh.backends.apsw.db import connect
from sqlalchemy.engine import create_engine

from transform.util import (
    convert_relative_date_to_timestamp,
    convert_time_to_isoformat,
    get_tech_stack,
    get_years_of_experience,
)

load_dotenv()
blacklist_db = "https://docs.google.com/spreadsheets/d/1Rp1yFWi6yJMhUGq2fkfGUhkmteScma5r9XkUEbqhq14/edit#gid=206068366"
all_listings_db = "https://docs.google.com/spreadsheets/d/1Rp1yFWi6yJMhUGq2fkfGUhkmteScma5r9XkUEbqhq14/edit#gid=1442393429"


def get_blacklist():
    connection = connect(":memory:")
    cursor = connection.cursor()
    SQL = f"""
    SELECT *
    FROM "{blacklist_db}"
    """
    rows = [row for row in cursor.execute(SQL)]
    return np.ravel(rows).tolist()


def parse(upload=False):
    metadata = {}
    pd.set_option("display.max_rows", None)

    df_linkedin = filter_data_to_df(
        "linkedin", convert_relative_date_to_timestamp, metadata
    )
    df_compjobs = filter_data_to_df("computerjobs", convert_time_to_isoformat, metadata)
    df_merged = pd.concat([df_linkedin, df_compjobs])

    engine = create_engine("shillelagh://")
    connection = engine.connect()
    SQL = f"""
    SELECT * FROM df_merged
    UNION
    SELECT * FROM "{all_listings_db}";
    """
    # cursor.execute(SQL)
    df_merged = pd.read_sql(SQL, connection)
    df_merged = df_merged.sort_values(by=["Date"], ascending=False)

    if upload or len(sys.argv) > 1 and sys.argv[1] == "--upload":
        gc = pygsheets.authorize(service_file="service_account_credential.json")

        sh = gc.open_by_key(os.getenv("GOOGLE_SHEETS_ID"))
        sh.worksheet_by_title("all_listings").set_dataframe(
            df_merged, "A1", copy_head=True
        )

        print(metadata)
        metadata_df = pd.DataFrame.from_dict(metadata)
        print(metadata_df)
        sh.worksheet_by_title("Metadata").set_dataframe(
            metadata_df, "A1", copy_head=True
        )


def filter_data_to_df(company: str, dateConversion, metadata: dict):
    date_format = "%m/%d/%Y %I:%M:%S %p %Z"
    date = datetime.now(tz=pytz.utc)
    date = date.astimezone(timezone("US/Pacific"))
    date = date.strftime(date_format)
    metadata["last_updated"] = [date]

    df = pd.read_csv(company + ".csv")
    df["Date"] = df["Date"].apply(dateConversion)
    df["Technologies"] = df["Description"].map(lambda x: ", ".join(get_tech_stack(x)))
    df["Years of Experience"] = df["Description"].map(get_years_of_experience)

    # set default values
    df["Senior"] = False
    df["Mid"] = False
    df["Intern"] = False
    df["Blacklist"] = False

    # mark all rows containing senior
    senior = ["Senior", "Sr.", "Staff", "Principal", "Manager", "Lead"]
    df["Senior"] = df.apply(
        lambda row: any(
            keyword.lower() in (row["Title"] + row["Description"]).lower()
            for keyword in senior
        ),
        axis=1,
    )

    # mark all rows containing mid
    mid = ["Mid", "II", "III"]
    df["Mid"] = df.apply(
        lambda row: any(
            keyword.lower() in (row["Title"] + row["Description"]).lower()
            for keyword in mid
        ),
        axis=1,
    )

    # mark all rows containing intern
    mid = ["Intern", "Internship"]
    df["Intern"] = df.apply(
        lambda row: any(
            keyword.lower() in (row["Title"] + row["Description"]).lower()
            for keyword in mid
        ),
        axis=1,
    )

    # mark all rows containing TS/SCI
    df["TS_SCI"] = df["Title"].str.contains("TS/SCI", case=False) | df[
        "Description"
    ].str.contains("TS/SCI", case=False)

    # sort by date posted
    df = df.sort_values(by=["Date"], ascending=False)

    # remove rows that contain blacklisted agencies
    blacklist = get_blacklist()
    df["Blacklist"] = df.apply(
        lambda row: any(
            keyword.lower() in row["Company"].lower() for keyword in blacklist
        ),
        axis=1,
    )

    # convert 2023-07-18T17:11:43.566939 to 2023-07-18
    df["Date"] = df["Date"].str.split("T").str[0]

    # convert nan to blank string
    df = df.fillna("")

    return df
