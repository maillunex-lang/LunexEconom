"""Offline/CLI operator roles; credentials are never accepted via public routes.

Usage: python -m server.platform.accounts_admin grant|revoke|list <username> [role]
"""
import argparse
import json
from server import db

ROLES=('player','developer','admin')


def main():
    parser=argparse.ArgumentParser(description='LunexEconom roles operator CLI')
    parser.add_argument('action',choices=('grant','revoke','list'))
    parser.add_argument('username')
    parser.add_argument('role',nargs='?',choices=ROLES)
    args=parser.parse_args()
    if args.action=='grant' and args.role not in ('developer','admin'):
        parser.error('grant role must be developer or admin')
    if args.action!='grant' and args.role is not None:
        parser.error('role is only applicable to grant')
    with db.connect() as conn:
        with conn.transaction():
            if args.action=='list':
                row=conn.execute('SELECT username,role,is_blocked FROM accounts WHERE lower(username)=lower(%s)',(args.username,)).fetchone()
                if not row:
                    parser.error('account not found')
                print(json.dumps({'username':row[0],'role':row[1],'blocked':row[2]}))
                return
            target=args.role if args.action=='grant' else 'player'
            row=conn.execute('UPDATE accounts SET role=%s WHERE lower(username)=lower(%s) RETURNING id,username',(target,args.username)).fetchone()
            if not row:
                parser.error('account not found')
            conn.execute('INSERT INTO audit(actor,action,payload) VALUES(%s,%s,%s)',('operator:cli','account.role',json.dumps({'username':row[1],'role':target})))
        conn.commit()
    print('Role updated:',args.username,target)

if __name__=='__main__': main()
