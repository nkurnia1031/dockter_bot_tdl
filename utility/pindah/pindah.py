import json
import os
from itertools import combinations
import multiprocessing
import queue
import re
import time


def parse_size(value):
    """Convert the shared Utility setting (for example ``750m``) to bytes."""
    match = re.fullmatch(r"([0-9]+(?:\.[0-9]+)?)([kmgt]?i?b?)?", value.strip().lower())
    if not match:
        raise ValueError(f"Ukuran tidak valid: {value}")
    number = float(match.group(1))
    unit = match.group(2) or "b"
    multipliers = {
        "b": 1,
        "k": 1024, "kb": 1024, "ki": 1024, "kib": 1024,
        "m": 1024**2, "mb": 1024**2, "mi": 1024**2, "mib": 1024**2,
        "g": 1024**3, "gb": 1024**3, "gi": 1024**3, "gib": 1024**3,
        "t": 1024**4, "tb": 1024**4, "ti": 1024**4, "tib": 1024**4,
    }
    return int(number * multipliers[unit])


def move_size_limit() -> int:
    return parse_size(os.getenv("UTILITY_MOVE_SIZE", "4g"))

def load_json(filename):
    """Membaca dan mengembalikan konten file JSON."""
    with open(filename, 'r') as f:
        return json.load(f)

def find_best_combination_worker(args):
    """Worker function to find the best combination within a given range of combination lengths."""
    items, space_left, r_start, r_end, progress_queue, stop_event, close_enough = args
    best_combination = []
    smallest_difference = space_left
    valid_combinations_count = 0

    for r in range(r_start, r_end):
        if stop_event.is_set():
            break
        for combination in combinations(items, r):
            if stop_event.is_set():
                break
            combined_size = sum(item[1] for item in combination)
            if combined_size <= space_left:
                difference = space_left - combined_size
                valid_combinations_count += 1
                progress_queue.put((multiprocessing.current_process().name, combined_size, difference, valid_combinations_count))
                if valid_combinations_count > 1000:
                    stop_event.set()
                    return best_combination, smallest_difference, valid_combinations_count
                    
                if difference < smallest_difference:
                    best_combination = [item[0] for item in combination]
                    smallest_difference = difference
                    if smallest_difference < close_enough:
                        stop_event.set()
                        return best_combination, smallest_difference, valid_combinations_count

    return best_combination, smallest_difference, valid_combinations_count

def find_best_combination(items, space_left, num_workers=4, close_enough=1 * 1024 * 1024):
    """Find the best combination of items to fill the space left using multiprocessing."""
    item_sizes = [(item['file'], item['size']) for item in items]
    total_items = len(item_sizes)
    best_combination = []
    smallest_difference = space_left
    valid_combinations_count = 0

    print(f'Finding best combination for space left: {space_left / (1024 * 1024 * 1024):.2f} GB')
    print(f'Total items to consider: {total_items}')

    chunk_size = (total_items + num_workers - 1) // num_workers  # ceil(total_items / num_workers)
    manager = multiprocessing.Manager()
    progress_queue = manager.Queue()
    stop_event = manager.Event()
    ranges = [(item_sizes, space_left, i * chunk_size + 1, min((i + 1) * chunk_size + 1, total_items + 1), progress_queue, stop_event, close_enough)
              for i in range(num_workers)]

    with multiprocessing.Pool(num_workers) as pool:
        async_results = [pool.apply_async(find_best_combination_worker, (range_args,)) for range_args in ranges]

        workers_done = [False] * num_workers
        while not all(workers_done):
            for i, res in enumerate(async_results):
                if res.ready() and not workers_done[i]:
                    workers_done[i] = True
                    result = res.get()
                    combination, difference, count = result
                    if difference < smallest_difference:
                        best_combination = combination
                        smallest_difference = difference
                        valid_combinations_count += count
            
            while not progress_queue.empty():
                try:
                    worker_name, combined_size, difference, count = progress_queue.get_nowait()
                    print(f'Worker {worker_name}: New best combination found with size {combined_size / (1024 * 1024 * 1024):.2f} GB and difference {difference / (1024 * 1024 * 1024):.2f} GB after {count} valid combinations')
                except queue.Empty:
                    pass
            
            time.sleep(1)  # Small sleep to prevent busy waiting

    print(f'Best combination size: {sum(item[1] for item in item_sizes if item[0] in best_combination) / (1024 * 1024 * 1024):.2f} GB')
    print(f'Best combination files: {best_combination}')
    print(f'Valid combinations checked: {valid_combinations_count}')

    return best_combination

def main():
    max_size = move_size_limit()
    # Preserve a small safety buffer without making low-size groups lose the
    # fixed 100 MB that used to be tailored only to the 4 GB default.
    safety_buffer = min(100 * 1024 * 1024, max(1 * 1024 * 1024, int(max_size * 0.025)))
    close_enough = max(1 * 1024 * 1024, int(max_size * 0.0125))
    print(f"Move group limit: {max_size / (1024 * 1024 * 1024):.2f} GB")
    data = load_json('output.json')
    
    for group in data.values():
        for item in group['items']:
            item['size'] = item['size'] * 1024 * 1024 * 1024  # Convert size to bytes

    processed_groups = {}
    unprocessed_groups = {key: value for key, value in data.items()}
    group_count = 1
    
    while unprocessed_groups:
        current_group_key = f'group_{group_count}'
        if current_group_key not in unprocessed_groups:
            break

        current_group = unprocessed_groups.pop(current_group_key)
        current_size = sum(item['size'] for item in current_group['items'])
        
        print(f'Processing {current_group_key} with current size {current_size / (1024 * 1024 * 1024):.2f} GB')

        if current_size < (max_size - safety_buffer):
            
            space_left = max_size - current_size
          
            
            print(f'{current_group_key} has {space_left / (1024 * 1024 * 1024):.2f} GB space left')
            
            all_other_items = [item for group in unprocessed_groups.values() for item in group['items']]
            
            best_combination_files = find_best_combination(
                all_other_items, space_left, close_enough=close_enough
            )
            best_combination_items = [item for item in all_other_items if item['file'] in best_combination_files]

            if not best_combination_items:
                print(f'No suitable items found for {current_group_key}. Stopping the loop.')
                break

            print(f'Adding {len(best_combination_items)} items to {current_group_key}')
            for item in best_combination_items:
                current_group['items'].append(item)
                for group in unprocessed_groups.values():
                    if item in group['items']:
                        group['items'].remove(item)

        current_group['total_size'] = sum(item['size'] for item in current_group['items']) / (1024 * 1024 * 1024)
        processed_groups[current_group_key] = current_group
        group_count += 1

        print(f'{current_group_key} processed with total size {current_group["total_size"]:.2f} GB\n')

    for group in processed_groups.values():
        for item in group['items']:
            item['size'] = item['size'] / (1024 * 1024 * 1024)  # Convert size to GB
    
    with open('new_output.json', 'w') as f:
        json.dump(processed_groups, f, indent=4)

    print(f'File dan folder telah dialokasikan ulang dan diekspor ke new_output.json.')

if __name__ == '__main__':
    main()
