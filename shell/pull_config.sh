if [ ! -f "/home/circleci/${CIRCLE_PROJECT_REPONAME}/bq_search_cron_deployment_config.txt" ]; then
    gsutil cp gs://${DEPLOYMENT_BUCKET}/bq_search_cron_deployment_config.txt /home/circleci/${CIRCLE_PROJECT_REPONAME}/
    chmod ugo+r /home/circleci/${CIRCLE_PROJECT_REPONAME}/bq_search_cron_deployment_config.txt
    if [ ! -f "/home/circleci/${CIRCLE_PROJECT_REPONAME}/bq_search_cron_deployment_config.txt" ]; then
      echo "[ERROR] Couldn't assign deployment configuration file bq_search_cron_deployment_config.txt - exiting."
      exit 1
    fi
    echo "Successfully copied the deployment configuration file bq_search_cron_deployment_config.txt."
else
    echo "Found deployment configuration file bq_search_cron_deployment_config.txt."
fi
