# import pymysql
# from fn_daily_management import daily_management
# from fn_account_approval import account_approval
from fn_bq_search_metadata import run_bq_metadata_etl
# CTB_CL_FN_DAILY_MANAGEMENT = 0
# CTB_CL_FN_ACCOUNT_APPROVAL = 1

if __name__ == "__main__":
    run_bq_metadata_etl(None)
