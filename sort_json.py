##################################################################
#       stocks_info.json 을 "name" 항목을 기준으로 오름차순 정렬    #  
##################################################################
import json

# JSON 파일 이름 및 경로
input_file_path = 'stocks_info.json'
output_file_path = 'sorted_stocks_info.json'

# JSON 파일 읽기 (인코딩 지정)
with open(input_file_path, 'r', encoding='utf-8') as input_file:
    data = json.load(input_file)

# "name" 항목을 기준으로 오름차순 정렬
sorted_data = dict(sorted(data.items(), key=lambda item: item[1]['name']))

# 새로운 JSON 파일로 저장 (인코딩 지정)
with open(output_file_path, 'w', encoding='utf-8') as output_file:
    json.dump(sorted_data, output_file, indent=4, ensure_ascii=False)

print(f'JSON 파일이 정렬되어 {output_file_path}에 저장되었습니다.')