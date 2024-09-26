from google.cloud import bigquery, storage
import json
from os import getenv
import re
import csv

STATIC_BUCKET_NAME = getenv("STATIC_BUCKET_NAME", 'webapp-static-files-isb-cgc-dev')
METADATA_FILE_PATH = getenv("METADATA_FILE_PATH", 'bq_ecosys/bq_meta_data.json')
FILTERS_FILE_PATH = getenv("FILTERS_FILE_PATH", 'bq_ecosys/bq_meta_filters.json')
JOIN_CSV_TO_JSON = bool(getenv("JOIN_CSV_TO_JSON", "True") == "True")
JOINS_CSV_FILE_PATH = getenv("JOINS_CSV_FILE_PATH", "bq_ecosys/bq_useful_join.csv")
JOINS_JSON_FILE_PATH = getenv("JOINS_JSON_FILE_PATH", "bq_ecosys/bq_useful_join.json")
VERSIONS_JSON_FILE_PATH = getenv("VERSIONS_JSON_FILE_PATH", "bq_ecosys/bq_versions.json")
MARKED_TABLE_MAP_FILE_PATH = getenv("MARKED_TABLE_MAP_FILE_PATH", 'bq_ecosys/bq_marked_tbl_map.json')

BQ_PROJECT_NAMES = getenv("BQ_PROJECT_NAMES", "isb-cgc/isb-cgc-bq")
BQ_ECO_SCAN_LABELS_ONLY = bool(getenv("BQ_ECO_SCAN_LABELS_ONLY", "False") == "True")
BQ_BUILD_VERSION_JSON = bool(getenv("BQ_BUILD_VERSION_JSON", "False") == "True")

METADATA_NUM_ROWS_END_STR = "-metadata_num_rows"
VIEW_ROW_COUNT_END_STR = "view_row_count"
METADATA_KEYS_TO_REMOVE = ['kind', 'etag', 'selfLink', 'numBytes', 'numLongTermBytes', 'location',
                           'numTimeTravelPhysicalBytes', 'numTotalLogicalBytes', 'numActiveLogicalBytes',
                           'numLongTermLogicalBytes', 'numTotalPhysicalBytes', 'numActivePhysicalBytes',
                           'numLongTermPhysicalBytes']
FILTERS = ['category', 'status', 'program', 'data_type', 'experimental_strategy', 'reference_genome', 'source',
           'project_id']

CATEGORY_DESCS = {
    "clinical_biospecimen_data": "Patient case and sample information ",
    "reference_database": "Genomic and Proteomic information that can be used to cross-reference with processed -omics data tables. (e.g. dbSNP)",
    "metadata": "Information about raw data files including Google Cloud Storage paths",
    "processed_-omics_data": "Processed data primarily from the GDC (e.g. raw data that has gone through GDC pipeline processing)"
}


def run_bq_metadata_etl(request):
    try:
        gcs = storage.Client()
        bucket = gcs.get_bucket(STATIC_BUCKET_NAME)
        # metadata update
        metadata_blob = bucket.get_blob(METADATA_FILE_PATH)
        filter_blob = bucket.get_blob(FILTERS_FILE_PATH)
        update_filter = False or not filter_blob
        new_tables_data = []
        if metadata_blob is None or check_for_update(metadata_blob.time_created):
            print('[INFO] METADATA FILE is outdated ...')
            new_tables_data_dict, new_bq_versions_dict = build_bq_metadata()
            new_tables_data = list(new_tables_data_dict.values())
            bucket.blob(METADATA_FILE_PATH).upload_from_string(json.dumps(new_tables_data),
                                                               content_type='application/json')
            if BQ_BUILD_VERSION_JSON:
                bucket.blob(VERSIONS_JSON_FILE_PATH).upload_from_string(json.dumps(new_bq_versions_dict),
                                                                        content_type='application/json')
                print('[INFO] VERSION FILE updated ...')
            print('[INFO] METADATA FILE updated ...')
            update_filter = True
        if update_filter:
            print('[INFO] FILTERS FILE is outdated ...')
            if not len(new_tables_data):
                if metadata_blob is None:
                    metadata_blob = bucket.get_blob(METADATA_FILE_PATH)
                else:
                    metadata_blob.reload()
                last_metadata_json_str = metadata_blob.download_as_string()
                new_tables_data = json.loads(last_metadata_json_str)
            bq_filters = build_filters(new_tables_data)
            bucket.blob(FILTERS_FILE_PATH).upload_from_string(json.dumps(bq_filters), content_type='application/json')
            print(f'[INFO] FILTERS FILE updated ...')

        # joins examples update
        if JOIN_CSV_TO_JSON:
            joins_csv_blob = bucket.get_blob(JOINS_CSV_FILE_PATH)
            joins_json_blob = bucket.get_blob(JOINS_JSON_FILE_PATH)
            if joins_csv_blob and (not joins_json_blob or joins_csv_blob.updated > joins_json_blob.time_created):
                print(f'[INFO] JOINS EXAMPLE JSON FILE is outdated ...')
                joins_list = update_example_joins_json(joins_csv_blob)
                joins_json_string = json.dumps(joins_list)
                bucket.blob(JOINS_JSON_FILE_PATH).upload_from_string(joins_json_string, content_type='application/json')
                print(f'[INFO] JOINS EXAMPLE JSON FILE updated ...')
    except Exception as e:
        print(f"[ERROR] Function <run_bq_metadata_etl> failed to run: {e}")
        return {"code": 500, "message": f"Function <run_bq_metadata_etl> failed to run: {e}"}
    message = "Function <run_bq_metadata_etl> ran successfully."
    print(f'[INFO] {message}')
    return {"code": 200, "message": message}


def build_bq_metadata():
    bq_table_metadata_dict = {}
    bq_versions_dict = {}
    gcs = storage.Client()
    bucket = gcs.get_bucket(STATIC_BUCKET_NAME)
    blob = bucket.get_blob(MARKED_TABLE_MAP_FILE_PATH)

    marked_tbl_map = json.loads(blob.download_as_string())
    project_name_list = BQ_PROJECT_NAMES.split('/')
    try:
        for project_name in project_name_list:
            print(f'[INFO] Building BQ Metadata: Scanning from project [{project_name}] ...')
            client = bigquery.Client(project=project_name)
            dataset_list = client.list_datasets(filter=('labels.bq_eco_scan' if BQ_ECO_SCAN_LABELS_ONLY else None))
            read_public_only = getenv('READ_PUBLIC_ONLY', 'True') == 'True'
            for dataset in dataset_list:
                read_this_dataset = False
                if dataset.dataset_id.startswith('bq_log') or dataset.dataset_id.startswith('bq_metrics'):
                    continue
                elif not read_public_only:
                    read_this_dataset = True
                else:
                    # check if dataset is public
                    ds_access_entries = client.get_dataset(dataset.dataset_id).access_entries
                    for access_entry in ds_access_entries:
                        if access_entry.role == 'READER' and access_entry.entity_type == 'specialGroup' and access_entry.entity_id == 'allAuthenticatedUsers':
                            read_this_dataset = True
                            break
                if read_this_dataset:
                    table_list = list(client.list_tables(dataset.dataset_id))
                    for tbl in table_list:
                        tbl_metadata = client.get_table(tbl).to_api_repr()
                        if BQ_BUILD_VERSION_JSON and tbl_metadata and 'labels' in tbl_metadata and 'version' in \
                                tbl_metadata['labels']:
                            tbl_prj_id = tbl_metadata['tableReference']['projectId']
                            tbl_ds_id = tbl_metadata['tableReference']['datasetId']
                            tbl_tbl_id = tbl_metadata['tableReference']['tableId']
                            labeled_version = tbl_metadata['labels']['version']
                            is_latest = ('status' in tbl_metadata['labels'] and tbl_metadata['labels'][
                                'status'] == 'current')
                            if tbl_ds_id.endswith('_versioned'):
                                root_tbl_ds_id = tbl_ds_id.removesuffix('_versioned')
                                tmp_tbl_id = tbl_tbl_id
                                if marked_tbl_map and tbl_ds_id in marked_tbl_map[tbl_prj_id]:
                                    for t in marked_tbl_map[tbl_prj_id][tbl_ds_id]:
                                        if tbl_tbl_id.startswith(t):
                                            tmp_tbl_id = tbl_tbl_id.replace(t, marked_tbl_map[tbl_prj_id][tbl_ds_id][t])
                                            break
                                root_tbl_tbl_id = tmp_tbl_id.removesuffix(f'_{labeled_version}'.lower())
                                root_tbl_tbl_id = root_tbl_tbl_id.removesuffix(f'_{labeled_version}'.upper())

                            elif tbl_tbl_id.endswith('_current'):
                                root_tbl_ds_id = tbl_ds_id
                                root_tbl_tbl_id = tbl_tbl_id.removesuffix('_current')
                                is_latest = True
                            version_root_id = f'{tbl_prj_id}:{root_tbl_ds_id}.{root_tbl_tbl_id}'
                            version_str = labeled_version.replace('_', '.')

                            if version_root_id not in bq_versions_dict:
                                bq_versions_dict[version_root_id] = {}
                            if version_str not in bq_versions_dict[version_root_id]:
                                bq_versions_dict[version_root_id][version_str] = {}
                            if 'is_latest' not in bq_versions_dict[version_root_id][version_str]:
                                bq_versions_dict[version_root_id][version_str]['is_latest'] = is_latest
                            else:
                                bq_versions_dict[version_root_id][version_str]['is_latest'] |= is_latest

                            if 'tables' not in bq_versions_dict[version_root_id][version_str]:
                                bq_versions_dict[version_root_id][version_str]['tables'] = []
                            bq_versions_dict[version_root_id][version_str]['tables'].append(
                                f'{tbl_prj_id}:{tbl_ds_id}.{tbl_tbl_id}')

                        for k in METADATA_KEYS_TO_REMOVE:
                            if k in tbl_metadata:
                                del tbl_metadata[k]
                        bq_table_metadata_dict[tbl_metadata['id']] = tbl_metadata
    except Exception as e:
        print(f"[ERROR] Error has occurred while running build_bq_metadata(): {e}")
    return bq_table_metadata_dict, bq_versions_dict


def build_filters(metadata_list):
    # create empty filter_data
    filter_data = {}
    # create empty options for each filter items
    for f in FILTERS:
        filter_data[f] = {
            "options": {}
        }
    for item in metadata_list:
        if 'labels' in item and item['labels']:
            for full_label_key, label_value in item['labels'].items():
                match = re.match(r'^\w+[^(?=_\d)]', full_label_key)
                filter_key = match.group(0) if match else match
                if filter_key in FILTERS:
                    if filter_key == 'category' and label_value == 'file_metadata':
                        label_value = 'metadata'
                    description = CATEGORY_DESCS[label_value] if filter_key == 'category' and CATEGORY_DESCS.get(
                        label_value) else ""
                    if label_value not in filter_data[filter_key]["options"]:
                        filter_data[filter_key]["options"][label_value] = {
                            'label': label_value.replace("_", " ").upper(),
                            'value': label_value,
                            'description': description
                        }
        if 'tableReference' in item and item['tableReference']:
            proj_id = item['tableReference']['projectId']
            filter_data["project_id"]["options"][proj_id] = {
                'label': proj_id,
                'value': proj_id,
                'description': ""
            }
    sorted_data = {}
    for k in filter_data:
        options = []
        if k == 'status' or k.startswith('reference_genome') or k.startswith('project_id'):
            options.append(
                {
                    'label': 'ALL',
                    'value': '',
                    'description': ''
                }
            )
        for op in sorted(filter_data[k]["options"]):
            options.append(filter_data[k]["options"][op])
        sorted_data[k] = {
            "options": options
        }
    return sorted_data


def update_example_joins_json(joins_csv_blob):
    print('[INFO] Running update_example_joins_json...')
    try:
        joins_csv_string = joins_csv_blob.download_as_text()
        print('[INFO] Reading Example Joins CSV file as text');
        reader = csv.reader(joins_csv_string.split("\r\n"), delimiter=',', quotechar='"')
        joins = {}
        cnt = 0
        for row in reader:
            cnt = cnt + 1
            if cnt == 1:
                # skip the table header
                continue
            progs = row[0].replace(" ", "").split(";")
            title = row[2]
            description = row[3]
            tables_templates = row[4].replace(" ", "").split(";")
            condition = row[5]
            query_template = row[6]
            for prog in progs:
                query = query_template.replace("[PROGRAM]", prog)
                tables = []
                for tbl_temp in tables_templates:
                    tbl = tbl_temp.replace("[PROGRAM]", prog).replace("isb-cgc-bq.", "isb-cgc-bq:")
                    tables.append(tbl)
                for tbl in tables:
                    joined_tables = [t for t in tables if t != tbl]
                    if tbl not in joins:
                        joins[tbl] = {"id": tbl, "joins": []}
                    joins[tbl]["joins"].append(
                        {
                            "title": title,
                            "description": description,
                            "tables": joined_tables,
                            "sql": query,
                            "condition": condition
                        })
        joins_arr = []
        for key, value in joins.items():
            joins_arr.append(value)
        print(f'[INFO] Processed {cnt} rows of joins data from file ...')
        return joins_arr

    except Exception as e:
        print(f"[ERROR] Function <update_example_joins_json> failed to run: {e}")


def check_for_update(last_updated):
    project_name_list = BQ_PROJECT_NAMES.split('/')
    update_needed = False
    try:
        for project_name in project_name_list:
            if update_needed:
                break
            print(f'[INFO] Checking for updates from project <{project_name}> ...')
            client = bigquery.Client(project=project_name)

            # dataset_list = client.list_datasets()
            dataset_list = client.list_datasets(filter=('labels.bq_eco_scan' if BQ_ECO_SCAN_LABELS_ONLY else None))

            read_public_only = getenv('READ_PUBLIC_ONLY', 'True') == 'True'
            for dataset in dataset_list:
                if update_needed:
                    break
                # print(f'[INFO] Scanning from === dataset <{dataset.dataset_id}> ...')
                read_this_dataset = False
                if dataset.dataset_id.startswith('bq_log') or dataset.dataset_id.startswith('bq_metrics'):
                    continue
                elif not read_public_only:
                    read_this_dataset = True
                else:
                    # check if dataset is public
                    ds_access_entries = client.get_dataset(dataset.dataset_id).access_entries
                    for access_entry in ds_access_entries:
                        if access_entry.role == 'READER' and access_entry.entity_type == 'specialGroup' and access_entry.entity_id == 'allAuthenticatedUsers':
                            read_this_dataset = True
                            break
                # print(f'read_this_dataset: {read_this_dataset}')
                if read_this_dataset:
                    table_list = list(client.list_tables(dataset.dataset_id))
                    for tbl in table_list:
                        t = client.get_table(tbl)
                        if last_updated < t.modified:
                            update_needed = True
                            print(
                                f'[INFO] Need to update METADATA FILE: Table {t.table_id} was recently added/modified.')
                            break

    except Exception as e:
        print(f"[ERROR] Error has occurred while running check_for_update(): {e}")
    return update_needed
