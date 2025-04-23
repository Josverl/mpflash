# update boardlist from zip 
import zipfile
import io
import sqlite3
import pandas as pd
from pathlib import Path
from mpflash.logger import log
HERE = Path(__file__).parent.resolve()

def load_data_from_zip(conn : sqlite3.Connection,zip_file: Path):
    log.debug("Loading data from zip file")
    csv_filename = 'micropython_boards.csv' # name of the .csv inside the .zip 

    # Check if the zip file exists
    if not zip_file.exists() or not zip_file.is_file():
        log.error(f"Zip file {zip_file} not found.")
        return
    conn.row_factory = sqlite3.Row  # return rows as dicts

    # Load data directly from the zip file
    with zipfile.ZipFile(zip_file, 'r') as zipf:
        # Read the CSV file from the zip
        with zipf.open(csv_filename) as csv_file:
            # Use pandas to read the CSV data
            df_boardlist = pd.read_csv(io.TextIOWrapper(csv_file, 'utf-8'))
            # Replace NaN values with empty strings to avoid NULL values in the database
            df_boardlist = df_boardlist.fillna('')
            # Insert data into the new SQLite database
            df_boardlist.to_sql('boards', conn, if_exists='replace', index=False)

    # Create indices for faster searching
    conn.execute('CREATE INDEX IF NOT EXISTS idx_version ON boards (version)')
    conn.execute('CREATE INDEX IF NOT EXISTS idx_id_version ON boards (board_id,version)')
    conn.execute('CREATE INDEX IF NOT EXISTS idx_descr ON boards (description)')

    conn.commit()



def load_jsonl_to_sqlite(jsonl_path: Path, conn: sqlite3.Connection, table_name = 'downloads',):
    """
    Load a JSONL file into a SQLite database using pandas.
    
    Args:
        jsonl_path (str or Path): Path to the JSONL file
        db_path (str or Path): Path to the SQLite database
    
    Returns:
        int: Number of records imported
    """
    log.debug("Loading JSONL file into SQLite database")
    # Ensure file exists
    if not jsonl_path.exists():
        raise FileNotFoundError(f"JSONL file not found: {jsonl_path}")
    
    # Read JSONL file into pandas DataFrame
    log.info("Reading JSONL file into DataFrame...")
    df = pd.read_json(jsonl_path, lines=True)
    record_count = len(df)
    
    if record_count == 0:
        log.info("JSONL file is empty")
        return 0
    # clean up the column names and data
    # Replace NaN values with empty strings to avoid NULL values in the database
    df = df.fillna('')
    #remove the url column
    if 'url' in df.columns:
        df = df.drop(columns=['url'])
    # rename the variant column to board_id
    if 'variant' in df.columns:
        df = df.rename(columns={'variant': 'board_id'})
    if 'firmware' in df.columns:
        df = df.rename(columns={'firmware': 'source'})

    # # change the preview and custom columns to boolean
    # for col in ['custom', 'preview']:
    #     if col in df.columns:
    #         df[col] = df[col].astype(bool)
    # Convert filename paths to POSIX format
    if 'filename' in df.columns:
        df['filename'] = df['filename'].apply(lambda x: Path(x).as_posix() if x else '')

    # append '-preview' to the version column if preview is True
    if 'preview' in df.columns:
        df['version'] = df.apply(lambda row: f"{row['version']}-preview" if row['preview'] else row['version'], axis=1)
        df = df.drop(columns=['preview'])


    # first remove all rows from the table
    conn.execute(f"DELETE FROM {table_name}")
    conn.commit()
    
    # Write DataFrame to SQLite
    log.info(f"Writing {record_count} records to database...")
    df.to_sql(table_name, conn, if_exists='append', index=False)
    
    # Create indices for faster searching
    cursor = conn.cursor()
    for col in df.columns:
        if col.lower() in ['board_id', 'filename', 'version']:
            cursor.execute(f'CREATE INDEX IF NOT EXISTS idx_dl_{col} ON {table_name} ("{col}")')
    
    conn.commit()
    
    log.info(f"Successfully imported {record_count} records")
    return record_count

