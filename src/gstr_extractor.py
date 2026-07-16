import json
import os
import base64
import xmlrpc.client
import pandas as pd
from datetime import datetime


def load_config(path=None):
    if path is None:
        script_dir = os.path.dirname(os.path.abspath(__file__))
        path = os.path.join(script_dir, '..', 'config.json')
    with open(path) as f:
        return json.load(f)


def get_odoo_connection(config):
    url = config['odoo']['url']
    db = config['odoo']['database']
    username = config['odoo']['username']
    password = config['odoo']['password']

    common = xmlrpc.client.ServerProxy(f'{url}/xmlrpc/2/common')
    uid = common.authenticate(db, username, password, {})
    if not uid:
        raise Exception("Odoo XML-RPC authentication failed")

    models = xmlrpc.client.ServerProxy(f'{url}/xmlrpc/2/object')
    return db, uid, models, password


def fetch_gstr_attachments(models, db, uid, password):
    domain = [
        ('name', 'ilike', 'gstr'),
        ('name', 'like', '.json'),
        ('res_model', '=', 'account.move'),
    ]

    attachments = models.execute_kw(
        db, uid, password,
        'ir.attachment', 'search_read',
        [domain],
        {'fields': ['id', 'name', 'create_date', 'datas', 'res_id', 'res_model'],
         'order': 'create_date desc',
         'limit': 0}
    )

    return attachments


def flatten_json(json_data, prefix=''):
    flattened = {}
    for key, value in json_data.items():
        new_key = f"{prefix}{key}" if not prefix else f"{prefix}.{key}"
        if isinstance(value, dict):
            flattened.update(flatten_json(value, new_key))
        elif isinstance(value, list):
            for i, item in enumerate(value):
                list_key = f"{new_key}[{i}]"
                if isinstance(item, dict):
                    flattened.update(flatten_json(item, f"{list_key}."))
                else:
                    flattened[list_key] = item
        else:
            flattened[new_key] = value
    return flattened


def gstr_json_to_rows(json_data):
    rows = []

    if isinstance(json_data, dict):
        gstin_data = json_data.get('data', json_data)

        if isinstance(gstin_data, dict) and 'data' in gstin_data:
            gstin_data = gstin_data['data']

        if isinstance(gstin_data, dict):
            for gstin, records in gstin_data.items():
                if not isinstance(records, dict):
                    rows.append({'gstin': gstin, 'value': records})
                    continue

                for section_key, section_data in records.items():
                    if not isinstance(section_data, list):
                        section_data = [section_data] if section_data else []

                    for record in section_data:
                        row = {'gstin': gstin, 'section': section_key}
                        if isinstance(record, dict):
                            row.update(record)
                        else:
                            row['value'] = record
                        rows.append(row)
        else:
            rows.append({'data': json.dumps(gstin_data, ensure_ascii=False)[:500]})

    elif isinstance(json_data, list):
        for item in json_data:
            if isinstance(item, dict):
                rows.append(item)
            else:
                rows.append({'value': item})

    return rows


def gstr_flat_json_to_rows(json_data, file_name=''):
    rows = []
    for key, value in json_data.items():
        row = {'field': key, 'value': value, 'source_file': file_name}
        rows.append(row)
    return rows


def download_and_convert_gstr(output_dir=None):
    if output_dir is None:
        output_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'gstr_output')
    os.makedirs(output_dir, exist_ok=True)

    config = load_config()
    db, uid, models, password = get_odoo_connection(config)

    print("Fetching GSTR attachments from Odoo...")
    attachments = fetch_gstr_attachments(models, db, uid, password)
    print(f"Found {len(attachments)} GSTR JSON files")

    if not attachments:
        print("No GSTR attachments found. Check if Odoo has fetched GSTR data.")
        return

    gstr_files = {'GSTR-1': [], 'GSTR-2A': [], 'GSTR-2B': [], 'OTHER': []}

    for att in attachments:
        name = att['name'].upper()
        if 'GSTR1' in name or 'GSTR-1' in name or 'GSTR_1' in name:
            gstr_files['GSTR-1'].append(att)
        elif 'GSTR2A' in name or 'GSTR-2A' in name or 'GSTR_2A' in name:
            gstr_files['GSTR-2A'].append(att)
        elif 'GSTR2B' in name or 'GSTR-2B' in name or 'GSTR_2B' in name:
            gstr_files['GSTR-2B'].append(att)
        else:
            gstr_files['OTHER'].append(att)

    print("\nFile breakdown:")
    for gstr_type, files in gstr_files.items():
        if files:
            print(f"  {gstr_type}: {len(files)} files")

    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')

    for gstr_type, files in gstr_files.items():
        if not files:
            continue

        all_rows = []
        seen_names = set()

        for att in files:
            if att['name'] in seen_names:
                continue
            seen_names.add(att['name'])

            try:
                raw_data = base64.b64decode(att['datas'])
                json_data = json.loads(raw_data.decode('utf-8'))
                print(f"\nProcessing: {att['name']}")

                if isinstance(json_data, dict):
                    row = {'source_file': att['name']}
                    row.update(json_data)
                    all_rows.append(row)
                    print(f"  Extracted 1 invoice")
                elif isinstance(json_data, list):
                    for item in json_data:
                        if isinstance(item, dict):
                            row = {'source_file': att['name']}
                            row.update(item)
                            all_rows.append(row)
                    print(f"  Extracted {len(json_data)} invoices")

            except json.JSONDecodeError as e:
                print(f"  WARNING: Invalid JSON in {att['name']}: {e}")
            except Exception as e:
                print(f"  ERROR processing {att['name']}: {e}")

        if all_rows:
            df = pd.DataFrame(all_rows)
            safe_name = gstr_type.replace('-', '_').replace(' ', '_')
            file_name = f"{safe_name}_{timestamp}.xlsx"
            file_path = os.path.join(output_dir, file_name)
            df.to_excel(file_path, index=False, engine='openpyxl')
            print(f"\nSaved: {file_path} ({len(df)} rows)")

    print(f"\nAll GSTR files saved to: {output_dir}")


if __name__ == '__main__':
    download_and_convert_gstr()
