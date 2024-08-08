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

DO_SETUP_APIS=FALSE
DO_SERVICE_ACCOUNT=FALSE
DO_SERVICE_ACCOUNT_AS_INVOKER=FALSE
DO_DEPLOYER_SA_IAM_POLICY_BINDING=FALSE
# FOR POST DEPLOYMENT SCRIPT
DO_BIND_FUNCTION_SA_TO_FUNCTION=TRUE

FUNCTION_SERVICE_NAME=bq-search-etl
LOCATION=us-west1

# DEV
DEPLOYMENT_PROJECT_ID=isb-cgc-dev-1
CLOUD_FUNCTION_SA=bq-search-cloud-function-sa@isb-cgc-dev-1.iam.gserviceaccount.com
CLOUD_SCHEDULER_SA=bq-search-cloud-scheduler@isb-cgc-dev-1.iam.gserviceaccount.com
DEPLOYER_SA=deployer@isb-cgc-dev-1.iam.gserviceaccount.com



## TEST
#DEPLOYMENT_PROJECT_ID=isb-cgc-test
#CLOUD_FUNCTION_SA=bq-search-cloud-function-sa@isb-cgc-test.iam.gserviceaccount.com
#CLOUD_SCHEDULER_SA=bq-search-dev-scheduler@isb-cgc-test.iam.gserviceaccount.com
#DEPLOYER_SA=deployer-test@isb-cgc-test.iam.gserviceaccount.com


# UAT
#DEPLOYMENT_PROJECT_ID=isb-cgc-uat
#CLOUD_FUNCTION_SA=bq-search-dev-cloud-function-sa@isb-cgc-uat.iam.gserviceaccount.com
#CLOUD_SCHEDULER_SA=bq-search-dev-scheduler@isb-cgc-uat.iam.gserviceaccount.com
#DEPLOYER_SA=deployer-uat@isb-cgc-uat.iam.gserviceaccount.com

## PROD
#DEPLOYMENT_PROJECT_ID=isb-cgc
#CLOUD_FUNCTION_SA=bq-search-dev-cloud-function-sa@isb-cgc.iam.gserviceaccount.com
#CLOUD_SCHEDULER_SA=bq-search-dev-scheduler@isb-cgc.iam.gserviceaccount.com
#DEPLOYER_SA=deployer@isb-cgc.iam.gserviceaccount.com



# Enable Cloud Functions, Cloud Build, Artifact Registry, Cloud Run, and Logging APIs.
if [ "${DO_SETUP_APIS}" == "TRUE" ]; then
    echo "------------------- DO_SETUP_APIS --------------------"
    GOOGLE_API_LIST=('run' 'cloudfunctions' 'artifactregistry' 'cloudresourcemanager')
    for api_item in "${GOOGLE_API_LIST[@]}"
    do
      RUN_IS_ENABLED=`gcloud services list --enabled --project=${DEPLOYMENT_PROJECT_ID} | grep ${api_item}.googleapis.com`
      if [ -z "${RUN_IS_ENABLED}" ]; then
        echo "Need to enable ${api_item} API"
        gcloud services enable ${api_item}.googleapis.com --project=${DEPLOYMENT_PROJECT_ID}
        echo "Waiting 120 seconds......"
        sleep 120
        echo "Done. Checking...."
        RUN_IS_ENABLED=`gcloud services list --enabled --project=${DEPLOYMENT_PROJECT_ID} | grep ${api_item}.googleapis.com`
        if [ -z "${RUN_IS_ENABLED}" ]; then
          echo "Enabling ${api_item} API failed"
          exit 1
        fi
        echo "${api_item} API is now enabled"
      else
        echo "${api_item} API is enabled"
      fi
    done
fi


if [ "${DO_SERVICE_ACCOUNT}" == "TRUE" ]; then
    echo "------------------ DO_SERVICE_ACCOUNT --------------------"
    GOOGLE_SA_LIST=(${CLOUD_FUNCTION_SA} ${CLOUD_SCHEDULER_SA})
    for sa_item in "${GOOGLE_SA_LIST[@]}"
    do
      SA_EXISTS=`gcloud iam service-accounts list --project=${DEPLOYMENT_PROJECT_ID} | grep ${sa_item}`
      if [ -z "${SA_EXISTS}" ]; then
        echo "Need to create service account ${sa_item}."
        SA_DISP_NAME="$(cut -d'@' -f1 <<<${sa_item})"
        gcloud iam service-accounts create ${SA_DISP_NAME} \
            --display-name ${SA_DISP_NAME} \
            --project ${DEPLOYMENT_PROJECT_ID}
        echo "Waiting 120 seconds......"
        sleep 120
        echo "Done. Checking...."
        SA_EXISTS=`gcloud iam service-accounts list --project=${DEPLOYMENT_PROJECT_ID} | grep ${sa_item}`
        if [ -z "${SA_EXISTS}" ]; then
            echo "Creating service account ${sa_item} failed."
            exit 1
          fi
          echo "Service account ${sa_item} is created successfully."
        else
          echo "Service account ${sa_item} already exists in the project."
        fi
    done
fi



if [ "${DO_SERVICE_ACCOUNT_AS_INVOKER}" == "TRUE" ]; then
    echo "------------------ DO_SERVICE_ACCOUNT_AS_INVOKER --------------------"
    # grant the scheduler SA with cloud run invoker roles
    gcloud projects add-iam-policy-binding ${DEPLOYMENT_PROJECT_ID} \
        --member serviceAccount:${CLOUD_SCHEDULER_SA} \
        --role roles/run.invoker --project ${DEPLOYMENT_PROJECT_ID}
fi


if [ "${DO_DEPLOYER_SA_IAM_POLICY_BINDING}" == "TRUE" ]; then
    echo "------------------ DO_DEPLOYER_SA_IAM_POLICY_BINDING --------------------"
    SAS_LIST=(${CLOUD_SCHEDULER_SA} ${CLOUD_FUNCTION_SA})
    for sa in "${SAS_LIST[@]}"
    do
      gcloud iam service-accounts add-iam-policy-binding ${sa} --member serviceAccount:${DEPLOYER_SA} \
        --role roles/iam.serviceAccountUser --project ${DEPLOYMENT_PROJECT_ID}
    done
fi

# POST DEPLOYMENT SCRIPTS
# bind the function service to the scheduler SA
if [ "${DO_BIND_FUNCTION_SA_TO_FUNCTION}" == "TRUE" ]; then
    echo "------------------ DO_BIND_FUNCTION_SA_TO_FUNCTION --------------------"
    gcloud functions add-invoker-policy-binding ${FUNCTION_SERVICE_NAME} \
          --region=${LOCATION} \
          --member=serviceAccount:${CLOUD_SCHEDULER_SA} --project ${DEPLOYMENT_PROJECT_ID}
fi


