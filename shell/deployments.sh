#!/usr/bin/env bash
#
# Copyright 2024 Institute for Systems Biology
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#   http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
#
DO_FUNCTION_DEPLOY=TRUE
DO_SETUP_SCHEDULER=TRUE

RUNTIME=python312
FUNCTION_SERVICE_NAME=bq-search-etl
ENTRY_POINT=run_bq_metadata_etl
LOCATION=us-west1
TIMEZONE=America/Los_Angeles

if [ "${DO_FUNCTION_DEPLOY}" == "TRUE" ]; then
    echo "------------------FUNCTION_DEPLOY--------------------"
    gcloud functions deploy ${FUNCTION_SERVICE_NAME} \
    --gen2 \
    --runtime ${RUNTIME} \
    --region ${LOCATION} \
    --service-account ${BQ_SEARCH_CLOUD_FUNCTION_SA} \
    --trigger-service-account ${BQ_SEARCH_CLOUD_SCHEDULER_SA} \
    --source ./cl_functions/src/ \
    --entry-point ${ENTRY_POINT} \
    --trigger-http \
    --timeout ${FUNCTION_TIMEOUT} \
    --set-env-vars STATIC_BUCKET_NAME=${STATIC_BUCKET_NAME},METADATA_FILE_PATH=${METADATA_FILE_PATH},FILTERS_FILE_PATH=${FILTERS_FILE_PATH},JOIN_CSV_TO_JSON=${JOIN_CSV_TO_JSON},JOINS_CSV_FILE_PATH=${JOINS_CSV_FILE_PATH},JOINS_JSON_FILE_PATH=${JOINS_JSON_FILE_PATH},BQ_PROJECT_NAMES=${BQ_PROJECT_NAMES},BQ_ECO_SCAN_LABELS_ONLY=${BQ_ECO_SCAN_LABELS_ONLY},BQ_BUILD_VERSION_JSON=${BQ_BUILD_VERSION_JSON},VERSIONS_JSON_FILE_PATH=${VERSIONS_JSON_FILE_PATH},READ_PUBLIC_ONLY=${READ_PUBLIC_ONLY}
fi

function setup_schedule {
    SCHEDULE_OP=$1
    FUNC_URL=`gcloud functions describe ${FUNCTION_SERVICE_NAME} \
              --gen2 --region ${LOCATION} --format="value(serviceConfig.uri)" --project ${DEPLOYMENT_PROJECT_ID}`

    # Change SCHEDULE_OP to update if you just want to change things after it is created:
    gcloud scheduler jobs ${SCHEDULE_OP} http ${FUNCTION_SERVICE_NAME}-trigger \
      --location ${LOCATION} \
      --schedule "${SCHEDULE_M} ${SCHEDULE_H} ${SCHEDULE_D} ${SCHEDULE_MO} ${SCHEDULE_W}" \
      --time-zone "${TIMEZONE}" \
      --uri ${FUNC_URL} \
      --message-body '{"purpose": "scheduled check"}' \
      --oidc-service-account-email ${BQ_SEARCH_CLOUD_SCHEDULER_SA} \
      --project ${DEPLOYMENT_PROJECT_ID} \
      --attempt-deadline 1200s \
      --description "A daily cron job to keep BQ Search current."
}


if [ "${DO_SETUP_SCHEDULER}" == "TRUE" ]; then
    echo "------------------SETUP SCHEDULER---------------------"
    SCHEDULE_JOB_EXISTS=`gcloud scheduler jobs describe ${FUNCTION_SERVICE_NAME}-trigger --location ${LOCATION} --project ${DEPLOYMENT_PROJECT_ID}`
    if [ -z "${SCHEDULE_JOB_EXISTS}" ]; then
        echo "------------------CREATE SCHEDULER---------------------"
        setup_schedule create
    else
        echo "------------------UPDATE SCHEDULER---------------------"
        setup_schedule update
    fi
fi
