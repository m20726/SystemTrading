import json
    
# stock_list_file_path = './stock_list.json'

def read_json_file(file_path):
    with open(file_path, 'r', encoding='UTF-8') as file:
        json_data = json.load(file)
        return json_data


def write_json_file(data, file_path):
    with open(file_path, 'w', encoding='UTF-8') as file:
        json.dump(data, file, indent=4)


# write_json_file(stock_list, stock_list_file_path)
# stock_list = read_json_file(stock_list_file_path)
# print(stock_list)


