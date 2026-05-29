"""
deduplicate_leads.py — Remove duplicate emails from firms.csv
"""
import csv
import os
import sys
import io

# Fix Windows console encoding
if sys.stdout.encoding != 'utf-8':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

import builtins
_original_print = builtins.print
def _flush_print(*args, **kwargs):
    kwargs.setdefault('flush', True)
    _original_print(*args, **kwargs)
builtins.print = _flush_print

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FIRMS_CSV = os.path.join(BASE_DIR, "firms.csv")

def remove_duplicates():
    print(f"\n{'='*56}")
    print(f"  DEDUPLICATOR — Cleaning firms.csv")
    print(f"{'='*56}\n")
    
    if not os.path.exists(FIRMS_CSV):
        print("❌ firms.csv not found.")
        return
        
    seen_emails = set()
    unique_rows = []
    duplicates = 0
    total = 0
    fieldnames = None
    
    try:
        with open(FIRMS_CSV, 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            fieldnames = reader.fieldnames
            for row in reader:
                total += 1
                email = row.get('contact_email', '').lower().strip()
                if email not in seen_emails and email != '':
                    seen_emails.add(email)
                    unique_rows.append(row)
                else:
                    duplicates += 1
                    
        if duplicates > 0:
            with open(FIRMS_CSV, 'w', newline='', encoding='utf-8') as f:
                writer = csv.DictWriter(f, fieldnames=fieldnames)
                writer.writeheader()
                writer.writerows(unique_rows)
            print(f"✅ Cleaned up {duplicates} duplicate leads.")
        else:
            print("✨ No duplicates found. Your leads are clean.")
            
        print(f"   Total before: {total}")
        print(f"   Total after:  {len(unique_rows)}")
        
    except Exception as e:
        print(f"❌ Error deduplicating leads: {e}")
        
    print(f"\n{'='*56}\n")

if __name__ == "__main__":
    remove_duplicates()
