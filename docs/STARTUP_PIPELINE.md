# Startup Pipeline

Creator Intelligence starts through these ordered stages:

1. Logging
2. Workspace initialization
3. Configuration
4. Database
5. Migrations
6. Optional backup
7. Modules and services
8. Diagnostics

Required failures abort startup. Optional failures are recorded in the lifecycle report and written to the log.
