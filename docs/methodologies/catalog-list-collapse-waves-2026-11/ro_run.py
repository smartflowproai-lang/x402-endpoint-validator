# Wrapper: wymusza PRAGMA query_only=1 na kazdym sqlite3.connect (B3) bez zmiany skryptow L-24; uruchamia skrypt przez runpy.
import sqlite3, runpy, sys
_c=sqlite3.connect
def _ro(*a,**k):
    assert 'mode=ro' in str(a[0]), 'tylko mode=ro'
    con=_c(*a,**k); con.execute('PRAGMA query_only=1')
    assert con.execute('PRAGMA query_only').fetchone()[0]==1
    return con
sqlite3.connect=_ro
sys.argv=sys.argv[1:]
runpy.run_path(sys.argv[0], run_name='__main__')
