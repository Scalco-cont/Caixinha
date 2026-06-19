import sqlite3

conn = sqlite3.connect('scalco.db')
cursor = conn.cursor()

# Reset companies
cursor.execute('''
    UPDATE empresas 
    SET status_lancamento_caixinha = 'pendente', 
        arquivo_gerado = NULL, 
        arquivo_rejeitado = NULL, 
        motivo_rejeicao = NULL, 
        dados_lancamento = '{}'
''')

# Delete baixas history to start fresh
cursor.execute('DELETE FROM baixas')

conn.commit()
print("Banco de dados resetado com sucesso. Tudo está pendente!")
