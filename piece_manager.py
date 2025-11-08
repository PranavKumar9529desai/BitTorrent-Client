"""
Piece Manager - Handles piece verification and assembly
"""
import os
import hashlib
from decoder import decoded_content


def get_piece_hashes():
    """
    Extracts piece hashes from the torrent file.
    
    Returns:
        list - List of 20-byte SHA1 hashes, one per piece
    """
    pieces_data = decoded_content['info']['pieces']
    num_pieces = len(pieces_data) // 20
    hashes = []
    
    for i in range(num_pieces):
        piece_hash = pieces_data[i*20:(i+1)*20]
        hashes.append(piece_hash)
    
    return hashes


def verify_piece(piece_index, piece_data, expected_hash):
    """
    Verifies a piece by comparing its SHA1 hash with the expected hash.
    
    Args:
        piece_index: int - Index of the piece
        piece_data: bytes - Complete piece data
        expected_hash: bytes - Expected 20-byte SHA1 hash
    
    Returns:
        bool - True if hash matches, False otherwise
    """
    actual_hash = hashlib.sha1(piece_data).digest()
    
    if actual_hash == expected_hash:
        print(f"✓ Piece {piece_index} verified successfully")
        return True
    else:
        print(f"✗ Piece {piece_index} verification failed!")
        print(f"  Expected: {expected_hash.hex()}")
        print(f"  Got:      {actual_hash.hex()}")
        return False


def is_piece_complete(pieces_dict, piece_index, expected_piece_length):
    """
    Checks if a piece is complete (has all blocks).
    
    Args:
        pieces_dict: dict - {piece_index: {offset: data}}
        piece_index: int - Index of piece to check
        expected_piece_length: int - Expected total length of piece
    
    Returns:
        bool - True if piece is complete
    """
    if piece_index not in pieces_dict:
        return False
    
    blocks = pieces_dict[piece_index]
    if not blocks:
        return False
    
    # Calculate total size of received blocks
    total_size = sum(len(data) for data in blocks.values())
    
    # Check if we have the expected size (allow small difference for last piece)
    if total_size < expected_piece_length - 100:  # Allow 100 bytes tolerance
        return False
    
    # Check if blocks are sequential (no gaps)
    sorted_offsets = sorted(blocks.keys())
    expected_offset = 0
    
    for offset in sorted_offsets:
        if offset != expected_offset:
            return False  # Gap in blocks
        expected_offset += len(blocks[offset])
    
    return True


def assemble_piece(pieces_dict, piece_index):
    """
    Assembles a complete piece from received blocks.
    
    Args:
        pieces_dict: dict - {piece_index: {offset: data}}
        piece_index: int - Index of piece to assemble
    
    Returns:
        bytes - Complete piece data, or None if incomplete
    """
    if piece_index not in pieces_dict:
        return None
    
    blocks = pieces_dict[piece_index]
    if not blocks:
        return None
    
    # Sort blocks by offset
    sorted_offsets = sorted(blocks.keys())
    
    # Check if we have all blocks (simple check - assumes sequential blocks)
    piece_data = b''
    expected_offset = 0
    
    for offset in sorted_offsets:
        if offset != expected_offset:
            print(f"Missing block at offset {expected_offset} in piece {piece_index}")
            return None  # Missing block
        
        piece_data += blocks[offset]
        expected_offset += len(blocks[offset])
    
    return piece_data


def save_piece_to_disk(piece_index, piece_data, output_dir='pieces'):
    """
    Saves a verified piece to disk.
    
    Args:
        piece_index: int - Index of piece
        piece_data: bytes - Complete piece data
        output_dir: str - Directory to save pieces
    
    Returns:
        str - Path to saved file, or None if failed
    """
    # Create output directory if it doesn't exist
    os.makedirs(output_dir, exist_ok=True)
    
    # Create filename: piece_00000.bin, piece_00001.bin, etc.
    filename = f"piece_{piece_index:05d}.bin"
    filepath = os.path.join(output_dir, filename)
    
    try:
        # Write piece to file
        with open(filepath, 'wb') as f:
            f.write(piece_data)
        
        file_size = len(piece_data)
        print(f"  Saved to: {filepath} ({file_size:,} bytes)")
        return filepath
    except Exception as e:
        print(f"  Error saving piece {piece_index}: {e}")
        return None


def load_piece_from_disk(piece_index, output_dir='pieces'):
    """
    Loads a piece from disk if it exists.
    
    Args:
        piece_index: int - Index of piece
        output_dir: str - Directory where pieces are stored
    
    Returns:
        bytes - Piece data if found, None otherwise
    """
    filename = f"piece_{piece_index:05d}.bin"
    filepath = os.path.join(output_dir, filename)
    
    if os.path.exists(filepath):
        try:
            with open(filepath, 'rb') as f:
                return f.read()
        except Exception as e:
            print(f"Error loading piece {piece_index}: {e}")
            return None
    return None


def get_saved_pieces(output_dir='pieces'):
    """
    Gets a list of all saved piece indices from disk.
    
    Args:
        output_dir: str - Directory where pieces are stored
    
    Returns:
        set - Set of piece indices that are saved on disk
    """
    saved = set()
    
    if not os.path.exists(output_dir):
        return saved
    
    for filename in os.listdir(output_dir):
        if filename.startswith('piece_') and filename.endswith('.bin'):
            try:
                # Extract piece index from filename: piece_00000.bin -> 0
                piece_index = int(filename[6:-4])  # Remove 'piece_' prefix and '.bin' suffix
                saved.add(piece_index)
            except ValueError:
                continue
    
    return saved


def verify_and_save_piece(piece_index, pieces_dict, piece_hashes, piece_length=262144, output_dir='pieces'):
    """
    Assembles, verifies, and saves a piece to disk.
    
    Args:
        piece_index: int - Index of piece
        pieces_dict: dict - Dictionary of received pieces
        piece_hashes: list - List of expected piece hashes
        piece_length: int - Expected length of piece (default 256 KB)
        output_dir: str - Directory to save pieces
    
    Returns:
        bool - True if piece was verified and saved successfully
    """
    if piece_index >= len(piece_hashes):
        print(f"Invalid piece index: {piece_index}")
        return False
    
    # Check if piece already exists on disk
    existing_piece = load_piece_from_disk(piece_index, output_dir)
    if existing_piece:
        # Verify existing piece
        expected_hash = piece_hashes[piece_index]
        if verify_piece(piece_index, existing_piece, expected_hash):
            print(f"Piece {piece_index} already exists and is valid")
            return True
        else:
            print(f"Piece {piece_index} on disk is corrupted, re-downloading...")
            # Remove corrupted piece
            filename = f"piece_{piece_index:05d}.bin"
            filepath = os.path.join(output_dir, filename)
            try:
                os.remove(filepath)
            except:
                pass
    
    # Check if piece is complete first
    if not is_piece_complete(pieces_dict, piece_index, piece_length):
        print(f"Piece {piece_index} is incomplete - skipping verification")
        return False
    
    # Assemble piece
    piece_data = assemble_piece(pieces_dict, piece_index)
    if not piece_data:
        print(f"Could not assemble piece {piece_index}")
        return False
    
    # Verify piece
    expected_hash = piece_hashes[piece_index]
    if not verify_piece(piece_index, piece_data, expected_hash):
        return False
    
    # Save piece to disk
    filepath = save_piece_to_disk(piece_index, piece_data, output_dir)
    if filepath:
        return True
    else:
        return False


def assemble_files_from_pieces(output_dir='downloads', pieces_dir='pieces'):
    """
    Assembles saved pieces into the actual files based on torrent structure.
    
    Args:
        output_dir: str - Directory to save assembled files
        pieces_dir: str - Directory where pieces are stored
    
    Returns:
        list - List of created file paths
    """
    info_dict = decoded_content['info']
    piece_length = info_dict.get('piece length', 262144)
    
    # Get all saved pieces
    saved_pieces = get_saved_pieces(pieces_dir)
    if not saved_pieces:
        print("No pieces found to assemble")
        return []
    
    print(f"\nAssembling files from {len(saved_pieces)} pieces...")
    
    # Create output directory
    os.makedirs(output_dir, exist_ok=True)
    
    # Get file structure from torrent
    files = info_dict.get('files', [])
    if not files:
        # Single file torrent
        file_name = info_dict.get('name', 'output')
        return assemble_single_file(file_name, saved_pieces, piece_length, 
                                   info_dict.get('length', 0), output_dir, pieces_dir)
    else:
        # Multi-file torrent
        return assemble_multi_file(files, saved_pieces, piece_length, output_dir, pieces_dir)


def assemble_single_file(file_name, saved_pieces, piece_length, total_length, output_dir, pieces_dir):
    """
    Assembles a single file from pieces.
    
    Args:
        file_name: str - Name of the file
        saved_pieces: set - Set of saved piece indices
        piece_length: int - Length of each piece
        total_length: int - Total file length
        output_dir: str - Output directory
        pieces_dir: str - Pieces directory
    
    Returns:
        list - List with single file path
    """
    filepath = os.path.join(output_dir, file_name)
    
    print(f"Assembling single file: {file_name}")
    
    with open(filepath, 'wb') as f:
        piece_index = 0
        bytes_written = 0
        
        while bytes_written < total_length:
            if piece_index in saved_pieces:
                piece_data = load_piece_from_disk(piece_index, pieces_dir)
                if piece_data:
                    # Calculate how much to write (last piece might be smaller)
                    remaining = total_length - bytes_written
                    write_size = min(len(piece_data), remaining)
                    f.write(piece_data[:write_size])
                    bytes_written += write_size
                    print(f"  Wrote piece {piece_index} ({write_size:,} bytes) - Total: {bytes_written:,}/{total_length:,} bytes")
                else:
                    print(f"  Warning: Piece {piece_index} not found, skipping")
            else:
                print(f"  Warning: Piece {piece_index} not saved, file will be incomplete")
                break
            
            piece_index += 1
    
    file_size = os.path.getsize(filepath)
    print(f"✓ File assembled: {filepath} ({file_size:,} bytes)")
    return [filepath]


def assemble_multi_file(files, saved_pieces, piece_length, output_dir, pieces_dir):
    """
    Assembles multiple files from pieces.
    
    Args:
        files: list - List of file dicts from torrent
        saved_pieces: set - Set of saved piece indices
        piece_length: int - Length of each piece
        output_dir: str - Output directory
        pieces_dir: str - Pieces directory
    
    Returns:
        list - List of created file paths
    """
    created_files = []
    current_piece_index = 0
    current_piece_offset = 0
    current_piece_data = None
    
    for file_info in files:
        file_path = file_info.get('path', [])
        file_length = file_info.get('length', 0)
        
        # Create full file path
        if isinstance(file_path, list):
            full_path = os.path.join(output_dir, *file_path)
        else:
            full_path = os.path.join(output_dir, file_path)
        
        # Create directory if needed
        os.makedirs(os.path.dirname(full_path), exist_ok=True)
        
        print(f"Assembling file: {'/'.join(file_path) if isinstance(file_path, list) else file_path}")
        
        with open(full_path, 'wb') as f:
            remaining = file_length
            bytes_written = 0
            
            while remaining > 0:
                # Load piece if needed
                if current_piece_data is None or current_piece_offset >= len(current_piece_data):
                    if current_piece_index in saved_pieces:
                        current_piece_data = load_piece_from_disk(current_piece_index, pieces_dir)
                        current_piece_offset = 0
                        if not current_piece_data:
                            print(f"  Warning: Piece {current_piece_index} not found")
                            break
                    else:
                        print(f"  Warning: Piece {current_piece_index} not saved")
                        break
                
                # Calculate how much to write from current piece
                available_in_piece = len(current_piece_data) - current_piece_offset
                write_size = min(remaining, available_in_piece)
                
                # Write data
                f.write(current_piece_data[current_piece_offset:current_piece_offset + write_size])
                bytes_written += write_size
                remaining -= write_size
                current_piece_offset += write_size
                
                # Move to next piece if current one is exhausted
                if current_piece_offset >= len(current_piece_data):
                    current_piece_index += 1
                    current_piece_data = None
                    current_piece_offset = 0
            
            file_size = os.path.getsize(full_path)
            print(f"  ✓ File assembled: {full_path} ({file_size:,} bytes)")
            created_files.append(full_path)
    
    return created_files

