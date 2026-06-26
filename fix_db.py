import sqlite3

def run():
    with sqlite3.connect('scalco.db') as conn:
        cursor = conn.cursor()
        # Find the ID of company 276
        cursor.execute("SELECT id, nome FROM empresas WHERE numero = '276'")
        row = cursor.fetchone()
        if row:
            emp_id, nome = row
            print(f"Found: {emp_id} - {nome}")
            
            # Delete from baixas to uncheck it
            cursor.execute("DELETE FROM baixas WHERE empresa_id = ?", (emp_id,))
            conn.commit()
            print(f"Deleted {cursor.rowcount} rows from baixas.")
        else:
            print("Company 276 not found.")

if __name__ == '__main__':
    run()
