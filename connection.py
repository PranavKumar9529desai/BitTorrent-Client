"""
BitTorrent Peer Connection Handler

Handles TCP connection, handshake, and Peer Wire Protocol message exchange.
Uses asyncio for concurrent multi-peer downloading.
"""
import socket
import struct
import asyncio
import time
from handshake import construct_handshake, validate_handshake
from messages import (
    create_interested, create_request, parse_message, parse_bitfield,
    parse_piece, MSG_BITFIELD, MSG_UNCHOKE, MSG_PIECE, MSG_CHOKE,
    create_keep_alive
)
from piece_manager import get_saved_pieces, is_piece_complete


def detect_ip_family(ip_address):
    """
    Detects if an IP address is IPv4 or IPv6.
    
    Args:
        ip_address: str - IP address string
    
    Returns:
        int - socket.AF_INET or socket.AF_INET6
    """
    if ':' in ip_address:
        return socket.AF_INET6
    else:
        return socket.AF_INET


async def async_receive_exact(reader, length, timeout=30):
    """
    Receives exactly 'length' bytes from async reader.
    
    Args:
        reader: asyncio.StreamReader - Async reader
        length: int - Number of bytes to receive
        timeout: int - Timeout in seconds
    
    Returns:
        bytes - Received data, or None if incomplete/timeout
    """
    data = b''
    try:
        while len(data) < length:
            remaining = length - len(data)
            chunk = await asyncio.wait_for(reader.read(remaining), timeout=timeout)
            if not chunk:
                return None  # Connection closed
            data += chunk
        return data
    except asyncio.TimeoutError:
        return None
    except Exception as e:
        print(f"Error receiving data: {e}")
        return None


async def async_connect_and_handshake(peer, info_hash, peer_id, timeout=10):
    """
    Connects to a peer, performs handshake, and returns reader/writer if successful.
    
    Args:
        peer: dict - {'ip': str, 'port': int}
        info_hash: bytes - 20-byte info hash
        peer_id: bytes - 20-byte peer ID
        timeout: int - Connection timeout in seconds
    
    Returns:
        tuple: (reader, writer, peer_peer_id) if successful, (None, None, None) if failed
    """
    try:
        print(f"[{peer['ip']}] Connecting...")
        
        # Async TCP connection
        reader, writer = await asyncio.wait_for(
            asyncio.open_connection(peer['ip'], peer['port']),
            timeout=timeout
        )
        print(f"[{peer['ip']}] TCP connection established")
        
        # Send handshake
        handshake_msg = construct_handshake(info_hash, peer_id)
        writer.write(handshake_msg)
        await writer.drain()
        print(f"[{peer['ip']}] Handshake sent")
        
        # Receive handshake response
        handshake_response = await async_receive_exact(reader, 68, timeout)
        if not handshake_response:
            print(f"[{peer['ip']}] Failed to receive handshake response")
            writer.close()
            await writer.wait_closed()
            return None, None, None
        
        # Validate handshake
        is_valid, peer_peer_id = validate_handshake(handshake_response, info_hash)
        if not is_valid:
            print(f"[{peer['ip']}] Handshake validation failed - wrong torrent")
            writer.close()
            await writer.wait_closed()
            return None, None, None
        
        print(f"[{peer['ip']}] Handshake successful! Peer ID: {peer_peer_id.hex()[:8]}...")
        return reader, writer, peer_peer_id
        
    except asyncio.TimeoutError:
        print(f"[{peer['ip']}] Connection/handshake timeout")
        return None, None, None
    except Exception as e:
        print(f"[{peer['ip']}] Connection failed: {e}")
        return None, None, None


async def async_exchange_messages(reader, writer, info_dict, peer_ip, timeout=30, pieces_dir='pieces', max_pieces_to_download=None, shared_state=None):
    """
    Exchanges Peer Wire Protocol messages with a peer (async version).
    
    Args:
        reader: asyncio.StreamReader - Async reader
        writer: asyncio.StreamWriter - Async writer
        info_dict: dict - Torrent info dictionary (for piece length)
        peer_ip: str - Peer IP address for logging
        timeout: int - Message timeout in seconds
        pieces_dir: str - Directory where pieces are saved
        max_pieces_to_download: int - Maximum pieces to download (None = all)
        shared_state: dict - Shared state for multi-peer coordination (optional)
    
    Returns:
        dict - {'bitfield': list, 'pieces': dict} or None if failed
    """
    buffer = b''
    bitfield = None
    unchoked = False
    pieces_received = {}  # {piece_index: {offset: data}}
    blocks_requested = {}  # {piece_index: set(offsets)} - Track requested blocks
    block_size = 16384  # 16 KB blocks
    max_concurrent_pieces = 15  # Download up to 15 pieces concurrently (increased for speed)
    
    # Calculate piece length
    piece_length = info_dict.get('piece length', 262144)  # Default 256 KB
    pieces_data = info_dict.get('pieces', b'')
    if isinstance(pieces_data, bytes):
        num_pieces = len(pieces_data) // 20
    else:
        num_pieces = 0
    
    # Get already saved pieces
    saved_pieces = get_saved_pieces(pieces_dir)
    print(f"Starting message exchange (expecting {num_pieces} pieces, {piece_length} bytes each)")
    print(f"Each piece needs {piece_length // block_size} blocks of {block_size} bytes")
    if saved_pieces:
        print(f"Found {len(saved_pieces)} pieces already saved on disk")
    
    # Determine which pieces to download
    if max_pieces_to_download:
        pieces_to_download = min(max_pieces_to_download, num_pieces)
    else:
        pieces_to_download = num_pieces
    
    pieces_downloading = set()  # Track which pieces we're currently downloading
    pieces_completed = set(saved_pieces)  # Track completed pieces (including saved ones)
    
    # Use shared state if provided (for multi-peer downloading)
    if shared_state:
        async with shared_state['lock']:
            pieces_completed = shared_state['pieces_completed'].copy()
            pieces_downloading = shared_state['pieces_downloading'].copy()
    
    # Keep-alive mechanism: send keep-alive every 2 minutes
    last_keepalive = time.time()
    keepalive_interval = 120  # 2 minutes
    
    try:
        # Send interested message
        interested_msg = create_interested()
        writer.write(interested_msg)
        await writer.drain()
        print(f"[{peer_ip}] Sent INTERESTED message")
        
        # Message exchange loop - continue until all pieces are downloaded
        while len(pieces_completed) < pieces_to_download:
            # Send keep-alive if needed
            current_time = time.time()
            if current_time - last_keepalive >= keepalive_interval:
                keepalive_msg = create_keep_alive()
                writer.write(keepalive_msg)
                await writer.drain()
                last_keepalive = current_time
            # Read data into buffer (async)
            # Use shorter timeout for reading, but check keep-alive separately
            read_timeout = min(60, timeout)  # Max 60 seconds for reading
            try:
                data = await asyncio.wait_for(reader.read(4096), timeout=read_timeout)
                if not data:
                    print(f"[{peer_ip}] Connection closed by peer")
                    break
                buffer += data
            except asyncio.TimeoutError:
                # Send keep-alive on timeout to maintain connection
                current_time = time.time()
                if current_time - last_keepalive >= keepalive_interval:
                    keepalive_msg = create_keep_alive()
                    writer.write(keepalive_msg)
                    await writer.drain()
                    last_keepalive = current_time
                
                # Check if we've completed all pieces before breaking
                if len(pieces_completed) >= pieces_to_download:
                    print(f"[{peer_ip}] All pieces completed!")
                    break
                # If we still have pieces to download, continue (maybe peer is slow)
                # But also check if we're making progress
                if len(pieces_downloading) == 0 and len(pieces_completed) < pieces_to_download:
                    # No pieces downloading and not all completed - might be stuck
                    print(f"[{peer_ip}] Timeout waiting for messages, but still need {pieces_to_download - len(pieces_completed)} pieces")
                    # Try to request more pieces if we're unchoked
                    if unchoked and bitfield:
                        await async_request_initial_blocks(writer, bitfield, piece_length, num_pieces, 
                                                          pieces_received, blocks_requested, pieces_downloading,
                                                          pieces_completed, pieces_to_download, block_size, 
                                                          shared_state, peer_ip)
                # Continue the loop instead of breaking
                continue
            
            # Process all complete messages in buffer
            while True:
                result = parse_message(buffer)
                if result is None:
                    break  # Incomplete message, wait for more data
                
                message_id, payload, bytes_consumed = result
                buffer = buffer[bytes_consumed:]
                
                # Handle keep-alive
                if message_id is None:
                    continue
                
                # Handle bitfield
                if message_id == MSG_BITFIELD:
                    bitfield = parse_bitfield(payload)
                    available_pieces = sum(bitfield)
                    print(f"[{peer_ip}] Received BITFIELD: {available_pieces}/{num_pieces} pieces available")
                
                # Handle unchoke
                elif message_id == MSG_UNCHOKE:
                    unchoked = True
                    print(f"[{peer_ip}] Received UNCHOKE - can now request pieces!")
                    
                    # Start requesting pieces if we have bitfield
                    if bitfield:
                        await async_request_initial_blocks(writer, bitfield, piece_length, num_pieces, 
                                                          pieces_received, blocks_requested, pieces_downloading,
                                                          pieces_completed, pieces_to_download, block_size, 
                                                          shared_state, peer_ip)
                
                # Handle choke
                elif message_id == MSG_CHOKE:
                    unchoked = False
                    print(f"[{peer_ip}] Received CHOKE - peer stopped sending data")
                
                # Handle piece
                elif message_id == MSG_PIECE:
                    piece_index, block_offset, block_data = parse_piece(payload)
                    if piece_index not in pieces_received:
                        pieces_received[piece_index] = {}
                    pieces_received[piece_index][block_offset] = block_data
                    
                    # Remove from requested set (we received it)
                    if piece_index in blocks_requested and block_offset in blocks_requested[piece_index]:
                        blocks_requested[piece_index].discard(block_offset)
                    
                    # Check if piece is now complete
                    if is_piece_complete(pieces_received, piece_index, piece_length):
                        if piece_index not in pieces_completed:
                            pieces_completed.add(piece_index)
                            pieces_downloading.discard(piece_index)
                            
                            # Update shared state if available
                            if shared_state:
                                async with shared_state['lock']:
                                    shared_state['pieces_completed'].add(piece_index)
                                    shared_state['pieces_downloading'].discard(piece_index)
                            
                            print(f"[{peer_ip}] ✓ Piece {piece_index} completed! ({len(pieces_completed)}/{pieces_to_download} pieces)")
                            
                            # Request next piece if we have room
                            if unchoked and bitfield and len(pieces_downloading) < max_concurrent_pieces:
                                await async_request_next_available_piece(writer, bitfield, piece_length, num_pieces,
                                                                        pieces_received, blocks_requested, pieces_downloading,
                                                                        pieces_completed, pieces_to_download, block_size,
                                                                        shared_state, peer_ip)
                    else:
                        # Show progress for incomplete pieces (less verbose)
                        if len(pieces_received[piece_index]) % 4 == 0:  # Print every 4 blocks
                            blocks_received = len(pieces_received[piece_index])
                            # Only print occasionally to reduce spam
                            pass
                    
                    # Check if we need to request more blocks for this piece
                    if unchoked and bitfield and bitfield[piece_index]:
                        await async_request_next_blocks(writer, piece_index, piece_length, num_pieces,
                                                        pieces_received, blocks_requested, block_size, peer_ip)
                
                else:
                    # Other messages (have, not interested, etc.) - just log
                    pass
        
        # Check if we completed all pieces
        if len(pieces_completed) >= pieces_to_download:
            print(f"[{peer_ip}] ✓ All {pieces_to_download} pieces completed!")
        
        return {
            'bitfield': bitfield,
            'pieces': pieces_received
        }
        
    except Exception as e:
        print(f"[{peer_ip}] Error in message exchange: {e}")
        import traceback
        traceback.print_exc()
        return None


async def async_request_initial_blocks(writer, bitfield, piece_length, num_pieces, 
                                      pieces_received, blocks_requested, pieces_downloading,
                                      pieces_completed, pieces_to_download, block_size, 
                                      shared_state, peer_ip):
    """
    Requests initial blocks from first available pieces that peer has (async version).
    
    Args:
        writer: asyncio.StreamWriter - Async writer
        bitfield: list - List of booleans indicating available pieces
        piece_length: int - Length of each piece
        num_pieces: int - Total number of pieces
        pieces_received: dict - Dictionary to store received pieces
        blocks_requested: dict - Dictionary to track requested blocks
        pieces_downloading: set - Set of piece indices currently being downloaded
        pieces_completed: set - Set of piece indices already completed
        pieces_to_download: int - Total number of pieces to download
        block_size: int - Size of each block to request (default 16 KB)
        shared_state: dict - Shared state for multi-peer coordination
        peer_ip: str - Peer IP for logging
    """
    if not bitfield:
        return
    
    max_concurrent = 15  # Start with 15 pieces concurrently (increased for speed)
    
    # Find pieces to download (not already completed, peer has them, not already downloading)
    for piece_index in range(min(pieces_to_download, len(bitfield))):
        # Check shared state if available
        can_download = True
        if shared_state:
            async with shared_state['lock']:
                if piece_index in shared_state['pieces_completed']:
                    can_download = False
                elif piece_index in shared_state['pieces_downloading']:
                    can_download = False
                else:
                    shared_state['pieces_downloading'].add(piece_index)
        
        if (can_download and
            piece_index not in pieces_completed and 
            piece_index not in pieces_downloading and
            bitfield[piece_index] and 
            len(pieces_downloading) < max_concurrent):
            
            # Initialize tracking
            if piece_index not in blocks_requested:
                blocks_requested[piece_index] = set()
            if piece_index not in pieces_received:
                pieces_received[piece_index] = {}
            
            # Request first block (offset 0)
            request_length = min(block_size, piece_length)
            request_msg = create_request(piece_index, 0, request_length)
            writer.write(request_msg)
            await writer.drain()
            blocks_requested[piece_index].add(0)
            pieces_downloading.add(piece_index)
            # Reduced logging for speed
            # print(f"[{peer_ip}] Requested piece {piece_index}, block 0")
            
            if len(pieces_downloading) >= max_concurrent:
                break


async def async_request_next_available_piece(writer, bitfield, piece_length, num_pieces,
                                             pieces_received, blocks_requested, pieces_downloading,
                                             pieces_completed, pieces_to_download, block_size,
                                             shared_state, peer_ip):
    """
    Requests the next available piece when a piece completes (async version).
    
    Args:
        writer: asyncio.StreamWriter - Async writer
        bitfield: list - List of booleans indicating available pieces
        piece_length: int - Length of each piece
        num_pieces: int - Total number of pieces
        pieces_received: dict - Dictionary of received pieces
        blocks_requested: dict - Dictionary tracking requested blocks
        pieces_downloading: set - Set of pieces currently downloading
        pieces_completed: set - Set of completed pieces
        pieces_to_download: int - Total pieces to download
        block_size: int - Size of each block
        shared_state: dict - Shared state for multi-peer coordination
        peer_ip: str - Peer IP for logging
    """
    if not bitfield:
        return
    
    # Find next piece to download
    for piece_index in range(min(pieces_to_download, len(bitfield))):
        # Check shared state if available
        can_download = True
        if shared_state:
            async with shared_state['lock']:
                if piece_index in shared_state['pieces_completed']:
                    can_download = False
                elif piece_index in shared_state['pieces_downloading']:
                    can_download = False
                else:
                    shared_state['pieces_downloading'].add(piece_index)
        
        if (can_download and
            piece_index not in pieces_completed and 
            piece_index not in pieces_downloading and
            bitfield[piece_index]):
            
            # Initialize tracking
            if piece_index not in blocks_requested:
                blocks_requested[piece_index] = set()
            if piece_index not in pieces_received:
                pieces_received[piece_index] = {}
            
            # Request first block
            request_length = min(block_size, piece_length)
            request_msg = create_request(piece_index, 0, request_length)
            writer.write(request_msg)
            await writer.drain()
            blocks_requested[piece_index].add(0)
            pieces_downloading.add(piece_index)
            # Reduced logging
            # print(f"[{peer_ip}] Requested piece {piece_index}, block 0")
            break


async def async_request_next_blocks(writer, piece_index, piece_length, num_pieces,
                                    pieces_received, blocks_requested, block_size, peer_ip):
    """
    Continues requesting more blocks for a piece as blocks are received (async version).
    
    Args:
        writer: asyncio.StreamWriter - Async writer
        piece_index: int - Index of piece to continue requesting
        piece_length: int - Length of each piece
        num_pieces: int - Total number of pieces
        pieces_received: dict - Dictionary of received blocks
        blocks_requested: dict - Dictionary tracking requested blocks
        block_size: int - Size of each block
        peer_ip: str - Peer IP for logging
    """
    if piece_index not in pieces_received:
        return
    
    # Calculate how many blocks this piece needs
    if piece_index == num_pieces - 1:
        # Last piece might be smaller
        blocks_needed = (piece_length + block_size - 1) // block_size
    else:
        blocks_needed = piece_length // block_size
    
    # Get blocks we already have
    received_offsets = set(pieces_received[piece_index].keys())
    
    # Find next block to request
    for block_num in range(blocks_needed):
        offset = block_num * block_size
        
        # Skip if we already have this block
        if offset in received_offsets:
            continue
        
        # Skip if we already requested this block
        if piece_index in blocks_requested and offset in blocks_requested[piece_index]:
            continue
        
        # Calculate request length (last block might be smaller)
        remaining = piece_length - offset
        request_length = min(block_size, remaining)
        
        # Request this block
        request_msg = create_request(piece_index, offset, request_length)
        writer.write(request_msg)
        await writer.drain()
        
        # Track that we requested it
        if piece_index not in blocks_requested:
            blocks_requested[piece_index] = set()
        blocks_requested[piece_index].add(offset)
        
        # Reduced logging for speed
        # print(f"[{peer_ip}] Requested piece {piece_index}, block {block_num}")
        break  # Request one block at a time


async def async_connect_to_peer(peer, info_hash, peer_id, info_dict, pieces_dir='pieces', max_pieces=None, shared_state=None):
    """
    Complete peer connection flow: TCP -> Handshake -> Messages (async version).
    
    Args:
        peer: dict - {'ip': str, 'port': int}
        info_hash: bytes - 20-byte info hash
        peer_id: bytes - 20-byte peer ID
        info_dict: dict - Torrent info dictionary
        pieces_dir: str - Directory to save pieces
        max_pieces: int - Maximum pieces to download (None = all)
        shared_state: dict - Shared state for multi-peer coordination
    
    Returns:
        dict - Results from message exchange or None
    """
    # Step 1: Connect and handshake
    reader, writer, peer_peer_id = await async_connect_and_handshake(peer, info_hash, peer_id)
    if not reader or not writer:
        return None
    
    try:
        # Step 2: Exchange messages
        result = await async_exchange_messages(reader, writer, info_dict, peer['ip'], timeout=120, 
                                              pieces_dir=pieces_dir, max_pieces_to_download=max_pieces,
                                              shared_state=shared_state)
        return result
    finally:
        writer.close()
        await writer.wait_closed()
        print(f"[{peer['ip']}] Connection closed")


async def connect(peer_list, info_hash, peer_id, info_dict, pieces_dir='pieces', max_pieces=None, max_peers=3):
    """
    Attempts to connect to multiple peers simultaneously using asyncio.
    If initial peers fail, retries with next peers from the list.
    
    Args:
        peer_list: list - List of peer dicts
        info_hash: bytes - 20-byte info hash
        peer_id: bytes - 20-byte peer ID
        info_dict: dict - Torrent info dictionary
        pieces_dir: str - Directory to save pieces
        max_pieces: int - Maximum pieces to download (None = all)
        max_peers: int - Maximum number of peers to connect to simultaneously (default 3)
    
    Returns:
        dict - Results from first successful peer connection, or None if all fail
    """
    # Shared state for all peer connections
    shared_state = {
        'pieces_completed': set(get_saved_pieces(pieces_dir)),
        'pieces_downloading': set(),
        'lock': asyncio.Lock(),
        'active_connections': []  # Track active connections
    }
    
    peer_index = 0
    successful_connections = []
    running_tasks = []  # Track tasks that are still running (successful connections)
    max_retries = 3  # Try up to 3 batches of peers
    
    print(f"\n{'='*60}")
    print(f"Connecting to peers (trying {max_peers} at a time, up to {max_retries} batches)...")
    print(f"{'='*60}")
    
    for batch in range(max_retries):
        if peer_index >= len(peer_list):
            print(f"\nNo more peers to try (tried {peer_index} peers)")
            break
        
        # Select next batch of peers
        batch_peers = peer_list[peer_index:peer_index + max_peers]
        peer_index += max_peers
        
        print(f"\nBatch {batch + 1}: Trying {len(batch_peers)} peers...")
        
        # Create tasks for this batch
        tasks = []
        for peer in batch_peers:
            task = asyncio.create_task(
                async_connect_to_peer(peer, info_hash, peer_id, info_dict, pieces_dir, max_pieces, shared_state)
            )
            tasks.append((task, peer))
        
        # Wait a short time to see if any connections establish
        # We check if tasks are still running after handshake (successful connection)
        # vs completed quickly (failed connection)
        try:
            # Wait 10 seconds to see connection status
            await asyncio.sleep(10)
            
            # Check which tasks are still running (likely successful connections)
            # vs completed (likely failed connections)
            batch_success = False
            batch_running_tasks = []
            
            for task, peer in tasks:
                if task.done():
                    # Task completed - check if it was successful
                    try:
                        result = await task
                        if result:
                            successful_connections.append((peer, result))
                            batch_success = True
                            print(f"[{peer['ip']}] ✓ Connection successful and completed!")
                    except Exception:
                        pass  # Failed connection, already logged
                else:
                    # Task still running - likely a successful connection that's downloading
                    batch_running_tasks.append((task, peer))
                    batch_success = True
                    print(f"[{peer['ip']}] ✓ Connection established and downloading...")
            
            # If we got at least one successful connection, keep those running
            if batch_success:
                running_tasks.extend(batch_running_tasks)  # Add to global running tasks
                print(f"\n✓ Got {len(successful_connections) + len(running_tasks)} successful connection(s)!")
                # Keep running tasks alive - they'll continue downloading
                # They coordinate via shared_state
                break
            else:
                # Cancel any pending tasks from this batch
                for task, peer in tasks:
                    if not task.done():
                        task.cancel()
                        try:
                            await task
                        except (asyncio.CancelledError, Exception):
                            pass
                
                print(f"Batch {batch + 1} failed - trying next batch...")
                
        except Exception as e:
            print(f"Error in batch {batch + 1}: {e}")
            # Cancel all tasks in this batch
            for task, peer in tasks:
                if not task.done():
                    task.cancel()
            continue
    
    # If we have successful connections (either completed or still running), wait for downloads
    if successful_connections or running_tasks:
        total_connections = len(successful_connections) + len(running_tasks)
        print(f"\n{'='*60}")
        print(f"Waiting for downloads to complete ({total_connections} active connection(s))...")
        print(f"{'='*60}")
        
        # Wait for all running tasks to complete (or fail)
        # Use asyncio.gather to wait for all, but don't fail if one fails
        if running_tasks:
            # Wait for all tasks, collecting results
            tasks_to_wait = [task for task, _ in running_tasks]
            try:
                # Wait for all tasks with return_exceptions=True so one failure doesn't stop others
                results = await asyncio.gather(*tasks_to_wait, return_exceptions=True)
                
                # Check results
                for i, result in enumerate(results):
                    peer = running_tasks[i][1]
                    if isinstance(result, Exception):
                        print(f"[{peer['ip']}] Connection ended with error: {result}")
                    elif result:
                        print(f"[{peer['ip']}] ✓ Connection completed successfully")
                        # Return first successful result
                        return result
            except Exception as e:
                print(f"Error waiting for tasks: {e}")
        
        # If we have a completed connection, return it
        if successful_connections:
            return successful_connections[0][1]
        
        # If all failed, return None
        return None
    else:
        print(f"\n✗ Failed to connect to any peers after trying {peer_index} peers")
        return None

