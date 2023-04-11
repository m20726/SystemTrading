import json
    
def read_json_file(file_path):
    with open(file_path, 'r', encoding='UTF-8') as file:
        json_data = json.load(file)
        return json_data


def write_json_file(data, file_path):
    with open(file_path, 'w', encoding='UTF-8') as file:
        json.dump(data, file, indent=4)