install:
	pip install -e .

run_api_local:
	uvicorn package_folder.api_file:app --reload --port 8000

build_container_local:
	docker build --tag=${IMAGE}:dev .

run_container_local:
	docker run -it -e PORT=8000 -p 8080:8000 ${IMAGE}:dev

build_for_production:
	docker build --platform linux/amd64 -t ${GCP_REGION}-docker.pkg.dev/${GCP_PROJECT}/${ARTIFACTSREPO}/${IMAGE}:prod .

push_image_production:
	docker push ${GCP_REGION}-docker.pkg.dev/${GCP_PROJECT}/${ARTIFACTSREPO}/${IMAGE}:prod

deploy_to_cloud_run:
	gcloud run deploy ${IMAGE} \
		--image ${GCP_REGION}-docker.pkg.dev/${GCP_PROJECT}/${ARTIFACTSREPO}/${IMAGE}:prod \
		--memory ${MEMORY} \
		--region ${GCP_REGION} \
		--project ${GCP_PROJECT} \
		--allow-unauthenticated

deploy: build_for_production push_image_production deploy_to_cloud_run

run_dashboard:
	streamlit run streamlit_app.py

garmin_update:
	python src/ingestion/garmin_parser.py && python src/ingestion/wellness_parser.py

load_duckdb:
	python src/ingestion/load_duckdb.py

garmin_full_update:
	python src/ingestion/garmin_parser.py && \
	python src/ingestion/wellness_parser.py && \
	python src/ingestion/load_duckdb.py

export_bigquery:
	python src/ingestion/export_bigquery.py

fetch_new_data:
	python src/ingestion/garmin_parser.py
	python src/ingestion/wellness_parser.py
	python src/ingestion/sync_daily.py
	python src/ingestion/load_duckdb.py
	python src/ingestion/export_bigquery.py

# ---------- one time bash command -----------
auth:
	gcloud auth configure-docker ${GCP_REGION}-docker.pkg.dev

check_permission:
	gcloud projects add-iam-policy-binding ${GCP_PROJECT} --member=user:${GCP_EMAIL} --role="roles/artifactregistry.writer"

create_artifact:
	gcloud artifacts repositories create ${ARTIFACTSREPO} --repository-format=docker --location=${GCP_REGION} --project=${GCP_PROJECT} --description="My Docker Artifact Repository"
