# Odoo Invoice Downloader

Automatically download invoices and vendor bills from Odoo and organize them locally by company and financial year.

## Features

- Downloads both customer invoices and vendor bills from Odoo
- Organizes files by company > financial year > Invoices/Bills
- Supports Odoo 19 (SaaS and self-hosted)
- Handles attachments and PDF generation
- Configurable financial year start month
- Can be scheduled to run automatically (e.g., every Wednesday)

## Project Structure

```
odoo-invoice-downloader/
├── src/
│   └── odoo_to_gdrive.py    # Main script
├── config.json               # Your configuration (not committed)
├── config.example.json       # Configuration template
├── requirements.txt          # Python dependencies
├── .gitignore
└── README.md
```

## Setup

### 1. Install Python Dependencies

```bash
pip install -r requirements.txt
```

### 2. Configure Odoo Connection

Copy `config.example.json` to `config.json` and fill in your details:

```json
{
    "odoo": {
        "url": "https://your-odoo-instance.odoo.com",
        "database": "your_database_name",
        "username": "your_email@example.com",
        "password": "your_xmlrpc_api_key",
        "web_password": "your_odoo_login_password"
    },
    "local_output": "Y:\\My Drive\\Odoo Invoices",
    "financial_year_start_month": 4,
    "invoice_types": ["out_invoice", "out_refund"],
    "bill_types": ["in_invoice", "in_refund"]
}
```

#### Getting Your API Key

1. Log in to Odoo
2. Go to **Settings** > **Users** > **Your Profile**
3. Under the **Account Security** tab, click **New API Key**
4. Copy the generated key and use it as the `password` field

### 3. Run the Script

```bash
python src/odoo_to_gdrive.py
```

## Output Structure

```
Odoo Invoices/
├── Company A/
│   ├── FY 2025-2026/
│   │   ├── Invoices/
│   │   │   ├── INV_25-26_001.pdf
│   │   │   └── ...
│   │   └── Bills/
│   │       ├── BILL_25-26_001.pdf
│   │       └── ...
│   └── FY 2026-2027/
│       ├── Invoices/
│       └── Bills/
├── Company B/
│   └── ...
└── Company C/
    └── ...
```

## Scheduling (Windows Task Scheduler)

To run this script automatically every Wednesday at 12:50 PM:

1. Open **Task Scheduler** (search in Windows Start menu)
2. Click **Create Basic Task**
3. Name: `Odoo Invoice Download`
4. Trigger: **Weekly** > Next > Select Wednesday
5. Start time: `12:50:00`
6. Action: **Start a program**
7. Program/script: Full path to Python executable (e.g., `C:\Users\YourName\.venv\Scripts\python.exe`)
8. Add arguments: Full path to script (e.g., `I:\opencode\src\odoo_to_gdrive.py`)
9. Start in: Script directory (e.g., `I:\opencode`)
10. Finish

Alternatively, run this PowerShell command:

```powershell
$action = New-ScheduledTaskAction -Execute "I:\opencode\.venv\Scripts\python.exe" -Argument "I:\opencode\src\odoo_to_gdrive.py" -WorkingDirectory "I:\opencode"
$trigger = New-ScheduledTaskTrigger -Weekly -DaysOfWeek Wednesday -At 12:50pm
Register-ScheduledTask -TaskName "Odoo Invoice Download" -Action $action -Trigger $trigger -Description "Download Odoo invoices every Wednesday"
```

## Notes

- The script uses two authentication methods:
  - **XML-RPC API key** for fetching invoice/bill data
  - **Web session login** (with your Odoo password) for downloading PDF reports
- If an invoice has attachments, those are downloaded first
- If no attachments exist, the PDF report is generated via Odoo's report engine
- The script is idempotent - running it multiple times won't create duplicates

## Requirements

- Python 3.10+
- Odoo instance with API access
- Google Drive sync folder (optional, for cloud backup)
