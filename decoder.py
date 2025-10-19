import bencode
# r+ is for read and write
# with open is used it automatically closes the file after the block

with open('fedora-2.torrent' , 'rb') as file :
    bencoded_content = file.read()

    # Decoding the bencoded content
    decoded_content = bencode.decode(bencoded_content)

    # print decoded_content 
    print(type(decoded_content)) # ord_dict as sequence of bytes is imp
    print(decoded_content.keys())

    for key in decoded_content:
        if key != 'info':
            print(f"{key} : {decoded_content[key]}") 

    info_dict = decoded_content['info']
    print("Info Dictionary Keys : ", info_dict.keys())

    # Number of Pieces 
    number_of_pieces = len(decoded_content["info"]["pieces"]) // 20 # as each hash if of 20 bytes
    print("Number of pieces",number_of_pieces)

    # calculate the file size
    for i in info_dict :
        if i != "pieces" :
            print(f"{i} : {info_dict[i]}")

    file_dict = info_dict["files"]
    size = 0
    for fl in file_dict :
        size+=fl["length"]
    
    print("Total size of file",size)