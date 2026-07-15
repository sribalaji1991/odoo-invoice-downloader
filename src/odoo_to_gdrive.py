import json
import os
import re
import shutil
import base64
import requests
import xmlrpc.client
from datetime import datetime


def load_config(path=None):
    if path is None:
        script_dir = os.path.dirname(os.path.abspath(__file__))
        path = os.path.join(script_dir, '..', 'config.json')
    with open(path) as f:
        return json.load(f)


def get_odoo_xmlrpc(config):
    url = config['odoo']['url']
    db = config['odoo']['database']
    username = config['odoo']['username']
    password = config['odoo']['password']

    common = xmlrpc.client.ServerProxy(f'{url}/xmlrpc/2/common')
    uid = common.authenticate(db, username, password, {})
    if not uid:
        raise Exception("Odoo XML-RPC authentication failed")

    models = xmlrpc.client.ServerProxy(f'{url}/xmlrpc/2/object')
    return db, uid, models


def get_odoo_session(config):
    url = config['odoo']['url']
    db = config['odoo']['database']
    username = config['odoo']['username']
    web_password = config['odoo']['web_password']

    session = requests.Session()
    login_page = session.get(f'{url}/web/login')
    csrf_match = re.search(r'csrf_token.*?value="(.*?)"', login_page.text)
    csrf_token = csrf_match.group(1) if csrf_match else ''

    login_resp = session.post(f'{url}/web/login', data={
        'db': db,
        'login': username,
        'password': web_password,
        'csrf_token': csrf_token,
    }, allow_redirects=False)

    if login_resp.status_code != 303:
        raise Exception(f"Odoo web login failed (status {login_resp.status_code})")

    return session


def download_report_pdf(session, config, invoice_id):
    url = config['odoo']['url']
    report_url = f'{url}/report/pdf/account.report_invoice_with_payments/{invoice_id}'
    response = session.get(report_url)
    if response.status_code == 200 and b'%PDF' in response.content[:10]:
        return response.content
    return None


def get_financial_year(date_str, start_month=4):
    date = datetime.strptime(date_str, '%Y-%m-%d')
    if date.month >= start_month:
        return f"{date.year}-{date.year + 1}"
    return f"{date.year - 1}-{date.year}"


def ensure_dir(path):
    os.makedirs(path, exist_ok=True)


def fetch_documents(models, db, uid, password, move_types):
    fields = [
        'id', 'name', 'invoice_date', 'partner_id',
        'company_id', 'move_type', 'state',
        'attachment_ids', 'amount_total', 'currency_id'
    ]

    domain = [
        ('move_type', 'in', move_types),
        ('state', '=', 'posted')
    ]

    docs = models.execute_kw(
        db, uid, password,
        'account.move', 'search_read',
        [domain],
        {'fields': fields, 'limit': 0}
    )

    return docs


def fetch_companies(models, db, uid, password):
    companies = models.execute_kw(
        db, uid, password,
        'res.company', 'search_read',
        [[]],
        {'fields': ['id', 'name']}
    )
    return {c['id']: c['name'] for c in companies}


def download_attachment(models, db, uid, password, attachment_id):
    attachment = models.execute_kw(
        db, uid, password,
        'ir.attachment', 'read',
        [[attachment_id]],
        {'fields': ['datas', 'name', 'mimetype']}
    )
    if not attachment:
        return None, None, None

    att = attachment[0]
    file_data = base64.b64decode(att['datas'])
    return file_data, att['name'], att['mimetype']


def reorganize_existing_files(local_output):
    print("Reorganizing existing files into Invoices/Bills subfolders...")
    if not os.path.exists(local_output):
        return

    for company_dir in os.listdir(local_output):
        company_path = os.path.join(local_output, company_dir)
        if not os.path.isdir(company_path):
            continue
        for fy_dir in os.listdir(company_path):
            fy_path = os.path.join(company_path, fy_dir)
            if not os.path.isdir(fy_path):
                continue
            if fy_dir in ("Invoices", "Bills"):
                continue

            invoices_sub = os.path.join(fy_path, "Invoices")
            bills_sub = os.path.join(fy_path, "Bills")

            for file_name in os.listdir(fy_path):
                file_path = os.path.join(fy_path, file_name)
                if not os.path.isfile(file_path):
                    continue

                name_upper = file_name.upper()
                if name_upper.startswith("INV") or name_upper.startswith("TLI"):
                    ensure_dir(invoices_sub)
                    shutil.move(file_path, os.path.join(invoices_sub, file_name))
                elif name_upper.startswith("BILL") or name_upper.startswith("RBILL") or name_upper.startswith("DBILL"):
                    ensure_dir(bills_sub)
                    shutil.move(file_path, os.path.join(bills_sub, file_name))
                else:
                    ensure_dir(invoices_sub)
                    shutil.move(file_path, os.path.join(invoices_sub, file_name))

    print("Reorganization complete.")


def process_documents(config):
    local_output = config.get('local_output', r"Y:\My Drive\Odoo Invoices")
    start_month = config.get('financial_year_start_month', 4)
    invoice_types = config.get('invoice_types', ['out_invoice', 'out_refund'])
    bill_types = config.get('bill_types', ['in_invoice', 'in_refund'])

    print("Connecting to Odoo XML-RPC...")
    db, uid, models = get_odoo_xmlrpc(config)
    api_password = config['odoo']['password']

    print("Connecting to Odoo web session...")
    odoo_session = get_odoo_session(config)

    companies = fetch_companies(models, db, uid, api_password)

    print("Fetching customer invoices...")
    invoices = fetch_documents(models, db, uid, api_password, invoice_types)
    print(f"  Found {len(invoices)} customer invoices")

    print("Fetching vendor bills...")
    bills = fetch_documents(models, db, uid, api_password, bill_types)
    print(f"  Found {len(bills)} vendor bills")

    ensure_dir(local_output)

    stats = {'total': len(invoices) + len(bills), 'saved': 0, 'skipped': 0, 'errors': 0}

    for i, inv in enumerate(invoices):
        try:
            inv_name = inv.get('name', f'INV-{inv["id"]}')
            inv_date = inv.get('invoice_date')
            if not inv_date:
                print(f"  [{i+1}/{stats['total']}] Skipping {inv_name} - no date")
                stats['skipped'] += 1
                continue

            company_id = inv['company_id'][0] if inv['company_id'] else None
            company_name = companies.get(company_id, 'Unknown Company')
            fy = get_financial_year(inv_date, start_month)

            company_dir = os.path.join(local_output, company_name)
            fy_dir = os.path.join(company_dir, f"FY {fy}", "Invoices")
            ensure_dir(fy_dir)

            saved = False

            if inv.get('attachment_ids'):
                for att_id in inv['attachment_ids']:
                    file_data, att_name, att_mimetype = download_attachment(
                        models, db, uid, api_password, att_id
                    )
                    if file_data:
                        safe_name = att_name.replace('/', '_').replace('\\', '_')
                        file_path = os.path.join(fy_dir, safe_name)
                        with open(file_path, 'wb') as f:
                            f.write(file_data)
                        print(f"  [{i+1}/{stats['total']}] Saved {safe_name}")
                        stats['saved'] += 1
                        saved = True

            if not saved:
                print(f"  [{i+1}/{stats['total']}] {inv_name} - downloading PDF...")
                pdf_bytes = download_report_pdf(odoo_session, config, inv['id'])
                if pdf_bytes:
                    safe_name = inv_name.replace('/', '_').replace('\\', '_')
                    file_name = f"{safe_name}.pdf"
                    file_path = os.path.join(fy_dir, file_name)
                    with open(file_path, 'wb') as f:
                        f.write(pdf_bytes)
                    print(f"  [{i+1}/{stats['total']}] Saved {file_name}")
                    stats['saved'] += 1
                else:
                    print(f"  [{i+1}/{stats['total']}] Failed to download PDF for {inv_name}")
                    stats['errors'] += 1

        except Exception as e:
            print(f"  [{i+1}/{stats['total']}] Error processing {inv.get('name', inv['id'])}: {e}")
            stats['errors'] += 1

    offset = len(invoices)
    for i, bill in enumerate(bills):
        try:
            bill_name = bill.get('name', f'BILL-{bill["id"]}')
            bill_date = bill.get('invoice_date')
            if not bill_date:
                print(f"  [{offset+i+1}/{stats['total']}] Skipping {bill_name} - no date")
                stats['skipped'] += 1
                continue

            company_id = bill['company_id'][0] if bill['company_id'] else None
            company_name = companies.get(company_id, 'Unknown Company')
            fy = get_financial_year(bill_date, start_month)

            company_dir = os.path.join(local_output, company_name)
            fy_dir = os.path.join(company_dir, f"FY {fy}", "Bills")
            ensure_dir(fy_dir)

            saved = False

            if bill.get('attachment_ids'):
                for att_id in bill['attachment_ids']:
                    file_data, att_name, att_mimetype = download_attachment(
                        models, db, uid, api_password, att_id
                    )
                    if file_data:
                        safe_name = att_name.replace('/', '_').replace('\\', '_')
                        file_path = os.path.join(fy_dir, safe_name)
                        with open(file_path, 'wb') as f:
                            f.write(file_data)
                        print(f"  [{offset+i+1}/{stats['total']}] Saved {safe_name}")
                        stats['saved'] += 1
                        saved = True

            if not saved:
                print(f"  [{offset+i+1}/{stats['total']}] {bill_name} - downloading PDF...")
                pdf_bytes = download_report_pdf(odoo_session, config, bill['id'])
                if pdf_bytes:
                    safe_name = bill_name.replace('/', '_').replace('\\', '_')
                    file_name = f"{safe_name}.pdf"
                    file_path = os.path.join(fy_dir, file_name)
                    with open(file_path, 'wb') as f:
                        f.write(pdf_bytes)
                    print(f"  [{offset+i+1}/{stats['total']}] Saved {file_name}")
                    stats['saved'] += 1
                else:
                    print(f"  [{offset+i+1}/{stats['total']}] Failed to download PDF for {bill_name}")
                    stats['errors'] += 1

        except Exception as e:
            print(f"  [{offset+i+1}/{stats['total']}] Error processing {bill.get('name', bill['id'])}: {e}")
            stats['errors'] += 1

    print(f"\nDone! Saved: {stats['saved']}, Skipped: {stats['skipped']}, Errors: {stats['errors']}")
    print(f"Output directory: {local_output}")


if __name__ == '__main__':
    config = load_config()
    local_output = config.get('local_output', r"Y:\My Drive\Odoo Invoices")
    reorganize_existing_files(local_output)
    process_documents(config)
