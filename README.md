The application will be hosted on **AWS App Runner** service.

Alternative thoughts: Lambda & API Gateway, EKS, EC2 instance.

### Prerequisites:

- AWS CLI installed and configured
- Terraform installed
- Docker installed
- OpenWeather API key

### Deployment Instructions

1. Login to your AWS account programmatically, so Terraform will be able to create resources on your behalf.
2. Set your OpenWeather API key as an environment variable in the following form:
```
export TF_VAR_openweather_api_key=<API key>
```
3. Run:
```
./deploy.sh
```
This will create the entire setup of the application using Terraform.

The app endpoint (`https://<App Runner hostname>/weather/`) will be displayed at the end of deployment process.
You can test the app by running `curl "<app URL>?city=<city>"`.

An ECR repository will be available for pushing new image tags for the app.

### Teardown

Run:
```
./delete.sh
```
This will delete the Terraform setup.