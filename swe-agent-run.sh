PROJECT_ROOT="files/swe-agent"
BATCH="batch_1"

sweagent run-batch --num_workers 1 \
    --instances.deployment.docker_args=--memory=10g \
    --config "${PROJECT_ROOT}/config.yaml" \
    --instances.path "${PROJECT_ROOT}/${BATCH}.yaml" \
    --output_dir "${PROJECT_ROOT}/output/${BATCH}" \
    --random_delay_multiplier=1