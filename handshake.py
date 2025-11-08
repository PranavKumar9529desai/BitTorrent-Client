PROTOCOL = b'BitTorrent protocol'

def construct_handshake(info_hash, peer_id): 
    """
    Constructs a BitTorrent handshake message (68 bytes total).
    
    Args:
        info_hash: bytes - 20-byte SHA1 hash of the torrent's info dict
        peer_id: bytes - 20-byte unique identifier for this peer
    
    Returns:
        bytes - Complete 68-byte handshake message
    """
    # Protocol string length (always 19)
    protocol_length = b'\x13'  # 19 in hex
    
    # Protocol string (exactly 19 bytes)
    protocol_string = PROTOCOL
    
    # Reserved bytes (8 zero bytes)
    reserved_bytes = b'\x00' * 8
    
    # Validate inputs
    if len(info_hash) != 20:
        raise ValueError(f"Info hash must be 20 bytes, got {len(info_hash)}")
    if len(peer_id) != 20:
        raise ValueError(f"Peer ID must be 20 bytes, got {len(peer_id)}")
    
    # Concatenate all parts: 1 + 19 + 8 + 20 + 20 = 68 bytes
    handshake = protocol_length + protocol_string + reserved_bytes + info_hash + peer_id
    
    return handshake


def parse_handshake(handshake_data):
    """
    Parses a received handshake message from a peer.
    
    Args:
        handshake_data: bytes - 68-byte handshake message received from peer
    
    Returns:
        tuple: (protocol_string, reserved_bytes, info_hash, peer_id)
    """
    if len(handshake_data) != 68:
        raise ValueError(f"Handshake must be 68 bytes, got {len(handshake_data)}")
    
    # Extract each part
    protocol_length = handshake_data[0]
    protocol_string = handshake_data[1:20]  # bytes 1-19
    reserved_bytes = handshake_data[20:28]  # bytes 20-27
    info_hash = handshake_data[28:48]       # bytes 28-47
    peer_id = handshake_data[48:68]         # bytes 48-67
    
    # Validate protocol string
    if protocol_length != 19:
        raise ValueError(f"Invalid protocol length: {protocol_length}")
    if protocol_string != PROTOCOL:
        raise ValueError(f"Invalid protocol string: {protocol_string}")
    
    return protocol_string, reserved_bytes, info_hash, peer_id


def validate_handshake(handshake_data, expected_info_hash):
    """
    Validates that a received handshake matches the expected torrent.
    
    Args:
        handshake_data: bytes - 68-byte handshake message from peer
        expected_info_hash: bytes - The info hash we expect (from our torrent)
    
    Returns:
        tuple: (is_valid, peer_id) - True if valid, and the peer's ID
    """
    try:
        _, _, received_info_hash, peer_id = parse_handshake(handshake_data)
        
        # Check if info hash matches (must be exact match)
        if received_info_hash != expected_info_hash:
            return False, None
        
        return True, peer_id
    except (ValueError, IndexError) as e:
        print(f"Handshake validation error: {e}")
        return False, None