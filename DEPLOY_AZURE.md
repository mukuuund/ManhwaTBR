# Deploying ManhwaTBR to Azure

This guide walks you through deploying the ManhwaTBR Flask application to Azure App Service Linux, and setting up the database on Azure Database for MySQL Flexible Server.

## 1. Prepare Your Database (Azure Database for MySQL Flexible Server)

### A. Create the MySQL Server
1. Go to the Azure Portal.
2. Search for **Azure Database for MySQL flexible servers**.
3. Click **Create** and select **Flexible Server**.
4. Fill out the details (Resource Group, Server Name, Region).
5. Choose the compute + storage size (Burstable B1ms is a good starting point for Azure for Students).
6. Set your Admin username and Password. Make sure you securely store this password!
7. In the **Networking** tab, ensure you check **Allow public access from any Azure service within Azure to this server**. This allows your App Service to talk to your database.
8. Click **Review + Create**.

### B. Export Local Database
Open your local terminal and run:
```bash
mysqldump -u root -p manhwa_tracker > manhwa_tracker_backup.sql
```

### C. Import into Azure MySQL
Once your Azure MySQL server is running, use its hostname to connect and import:
```bash
# Connect and create the empty database first
mysql -h <your-azure-mysql-hostname>.mysql.database.azure.com -u <admin-username> -p -e "CREATE DATABASE manhwa_tracker;"

# Import the data
mysql -h <your-azure-mysql-hostname>.mysql.database.azure.com -u <admin-username> -p manhwa_tracker < manhwa_tracker_backup.sql
```

---

## 2. Prepare the Web App (Azure App Service Linux)

### A. Create the App Service
1. In the Azure Portal, create a new **Web App**.
2. Select your Resource Group.
3. Give it a name (e.g., `manhwatbr-app`).
4. Publish: **Code**.
5. Runtime Stack: **Python 3.11** (or matching your version).
6. Operating System: **Linux**.
7. Region: Same region as your MySQL server.
8. App Service Plan: Free (F1) or Basic (B1) for students.
9. Click **Review + Create**.

### B. Configure Environment Variables
In your new Web App, go to **Settings > Environment variables** (or Configuration > Application settings in older UI). Add the following variables:

| Name | Value |
|------|-------|
| `DB_HOST` | `<your-azure-mysql-hostname>.mysql.database.azure.com` |
| `DB_PORT` | `3306` |
| `DB_USER` | `<admin-username>` |
| `DB_PASSWORD` | `<your-secure-password>` |
| `DB_NAME` | `manhwa_tracker` |
| `SECRET_KEY` | `generate-a-strong-random-key-here` |
| `FLASK_ENV` | `production` |
| `FLASK_DEBUG` | `False` |
| `ASURA_ENABLED` | `true` |

*Optionally, if you are using Telegram scanning online, you can also add `TELEGRAM_API_ID` and `TELEGRAM_API_HASH`.*

### C. Configure Startup Command
Still in **Settings > Configuration** (or Environment variables), find the **General settings** tab. 
In the **Startup Command** box, enter exactly:
```bash
gunicorn --bind=0.0.0.0 --timeout 600 app:app
```

### D. Deploy the Code
You can deploy your code in several ways:
- **GitHub Actions**: If you push this repository to GitHub, you can link it via the **Deployment Center** in the Azure Portal, and Azure will generate a deployment pipeline for you.
- **VS Code Azure App Service Extension**: Right-click your project folder in VS Code, select "Deploy to Web App...", and select your Azure app.
- **Azure CLI**: `az webapp up --name manhwatbr-app --resource-group <Your-Resource-Group> --runtime "PYTHON:3.11"`

---

## 3. How the Cloud "Import Folder" Works

The Import Folder feature is fully cloud-compatible out-of-the-box!
- It does **not** rely on the `MANHWA_FOLDER` setting anymore.
- Users can click **Upload Manhwa Folder** or **Import Files** in the web interface.
- Files are securely sent to the server's temporary storage.
- The server infers titles and chapters from the folder names (e.g. `Solo Leveling/Chapter 1/page.jpg`).
- The database is updated, and the temporary files are instantly deleted to save storage.
- *(Note: Azure Blob Storage is not used or needed right now because files are only used for temporary metadata extraction.)*

---

## Troubleshooting
- **500 Internal Server Error**: Check the Log Stream in Azure Portal (under Monitoring) to see the exact Python exception.
- **Database Connection Failed**: Double check your `DB_HOST`, `DB_USER`, and `DB_PASSWORD`. Make sure "Allow public access from any Azure service" is enabled on the MySQL server.
- **Missing Module**: Make sure you deployed the `requirements.txt` file properly. Azure will automatically run `pip install -r requirements.txt` during deployment.
