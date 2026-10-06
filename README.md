# Job Extractor v2.1

A modularized job extraction system that fetches job data from Greenhouse API, processes it, and stores it in MongoDB.

## Project Structure

```
job extractor v2.1/
├── main.py              # Main entry point
├── config.py            # Configuration and environment variables
├── models.py            # Pydantic data models
├── database.py          # MongoDB connection and operations
├── parser.py            # Job data parsing and extraction
├── greenhouse.py        # Greenhouse API interactions
├── service.py           # Main orchestration service
├── requirements.txt     # Python dependencies
└── README.md           # This file
```

## Modules Overview

### `main.py`
- Simple entry point that starts the job extraction server
- Handles basic error handling and logging setup

### `config.py`
- Environment variable management
- Skills categories and constants
- Database configuration settings
- Logging setup

### `models.py`
- Pydantic models for data validation:
  - `JobData`: Extracted job information
  - `LocationResult`: Parsed location data
  - `JobMongo`: Complete job document for MongoDB
  - `JobDescriptionTokensMongo`: Token data for search

### `database.py`
- `DatabaseManager` class handles all MongoDB operations:
  - Connection management with retry logic
  - Company data fetching
  - Job insertion and duplicate checking
  - Token storage
  - Company status updates

### `parser.py`
- `JobPostingParser` class for data extraction:
  - HTML content cleaning
  - Pattern-based extraction (workplace type, job type, experience, salary)
  - Geocoding with rate limiting and caching
  - spaCy-based token extraction

### `greenhouse.py`
- `GreenhouseAPI` class for API interactions:
  - Job data fetching from Greenhouse API
  - Content cleaning and validation
  - Error handling for different response codes

### `service.py`
- `JobExtractionService` orchestrates the entire process:
  - Coordinates between all modules
  - Processes companies and jobs sequentially
  - Handles the complete workflow

## Setup

1. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```

2. Install spaCy English model:
   ```bash
  pip install -U https://github.com/explosion/spacy-models/releases/download/en_core_web_sm-3.7.1/en_core_web_sm-3.7.1-py3-none-any.whl
   ```

3. Create a `.env` file with your configuration:
   ```
   DEV_MONGODB_URI=your_mongodb_connection_string
   LOGTAIL_TOKEN=pBEMdxLpyAdW6C9ezLvMjaeq
   ENVIRONMENT=production
   HOSTNAME=job-extractor-server
   ```

## Running the Application

Simply run the main script:

```bash
python main.py
```

## Azure VM CI/CD

The production flow for this repo is:

1. GitHub Actions deploys the repository to your Azure VM on every merge to `main`.
2. The VM keeps a local virtual environment in the deployment directory.
3. A cron job runs `cron_runner.sh`, which activates the venv and executes `runner.py`.

Required GitHub secrets:

- `AZURE_VM_HOST`
- `AZURE_VM_USER`
- `AZURE_VM_SSH_KEY`

One-time cron example on the VM:

```bash
*/15 * * * * /home/<vm-user>/job-extractor/cron_runner.sh >> /var/log/job-extractor.log 2>&1
```

Adjust the schedule to match how often you want the worker to run.

## Remote Logging

The application includes remote logging via Logtail (Better Stack):

- **Real-time Monitoring**: Logs are sent to your Logtail dashboard in real-time
- **Dual Logging**: Both local console logging and remote logging are active
- **Structured Data**: JSON logging with timestamps, levels, and metadata
- **Easy Access**: View logs remotely at https://logtail.com/ using your account
- **Production Ready**: Perfect for monitoring when deployed on EC2 or other cloud instances

## Key Features

- **Modular Design**: Clean separation of concerns
- **Error Handling**: Comprehensive error handling throughout
- **Rate Limiting**: Geocoding API rate limiting to avoid timeouts
- **Caching**: Location data caching to reduce API calls
- **Remote Logging**: Real-time log monitoring via Logtail/Better Stack
- **Data Validation**: Pydantic models ensure data integrity
- **Database Safety**: Connection pooling and retry logic

## Environment Variables

- `DEV_MONGODB_URI`: MongoDB connection string (required)
- `LOGTAIL_TOKEN`: Your Logtail authentication token (for remote logging)
- `ENVIRONMENT`: Application environment (e.g., production, development)
- `HOSTNAME`: Server hostname for log identification

## Dependencies

- `certifi`: SSL certificate verification
- `geopy`: Geocoding services
- `pymongo`: MongoDB Python driver
- `pydantic`: Data validation and settings management
- `python-dotenv`: Environment variable loading
- `requests`: HTTP library for API calls
- `spacy`: Natural language processing
- `beautifulsoup4`: HTML parsing (if needed for future extensions)

This modular structure makes the code much easier to maintain, test, and extend.