import json
    
# stock_list_file_path = './stock_list.json'

def read_json_file(file_path):
    with open(file_path, 'r', encoding='UTF-8') as file:
        json_data = json.load(file)
        return json_data


def write_json_file(data, file_path):
    with open(file_path, 'w', encoding='UTF-8') as file:
        json.dump(data, file, indent=4)


# stock_list = [
#     {'name':'삼성전자', 'code':'005930', 'envelope_p':10, 'sell_target_p':7},
#     {'name':'셀트리온', 'code':'068270', 'envelope_p':8, 'sell_target_p':11}
# ]

# write_json_file(stock_list, stock_list_file_path)
# stock_list = read_json_file(stock_list_file_path)
# print(stock_list)


