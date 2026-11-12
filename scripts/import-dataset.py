import json
import csv
import os

def convert_csv_to_catalog(csv_filepath, output_filepath):
    catalog = []
    if os.path.exists(output_filepath):
        with open(output_filepath, 'r', encoding='utf-8') as f:
            catalog = json.load(f)

    with open(csv_filepath, mode='r', encoding='utf-8') as csv_file:
        reader = csv.DictReader(csv_file)
        for idx, row in enumerate(reader, start=len(catalog) + 1):
            screen_entry = {
                "id": f"ui_{idx:06d}",
                "app_name": row.get("app_name", "Unknown App"),
                "category": row.get("category", "General"),
                "platform": row.get("platform", "iOS"),
                "flow": row.get("flow", "Main"),
                "step": int(row.get("step", 1)),
                "tags": [t.strip() for t in row.get("tags", "").split(",") if t.strip()],
                "image_url": row.get("image_url", ""),
                "ui_code_snippet": row.get("ui_code_snippet", "")
            }
            catalog.append(screen_entry)

    with open(output_filepath, 'w', encoding='utf-8') as f:
        json.dump(catalog, f, indent=2)
    print(f"Successfully imported! Total screens in catalog: {len(catalog)}")

if __name__ == "__main__":
    # Example usage: place a 'raw_screens.csv' file in the scripts folder
    if os.path.exists("raw_screens.csv"):
        convert_csv_to_catalog("raw_screens.csv", "../data/catalog.json")
    else:
        print("Create a 'raw_screens.csv' file to bulk import screens.")
      
