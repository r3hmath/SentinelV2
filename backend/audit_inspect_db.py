import asyncio
import asyncpg

async def inspect():
    conn = await asyncpg.connect("postgresql://postgres:admin@127.0.0.1:5433/sentinel")
    rows = await conn.fetch("""
        SELECT tablename, indexname, indexdef 
        FROM pg_indexes 
        WHERE schemaname = 'public' 
          AND tablename IN ('cameras', 'events', 'egujcop_watchlist')
        ORDER BY tablename, indexname;
    """)
    print("INDEXES FOUND:")
    for r in rows:
        print(f"  {r['tablename']}.{r['indexname']} -> {r['indexdef']}")
    
    # Check postgis extension
    ext = await conn.fetch("SELECT extname, extversion FROM pg_extension WHERE extname = 'postgis'")
    print("\nPOSTGIS EXTENSION:")
    for e in ext:
        print(f"  {e['extname']}: {e['extversion']}")
    
    # Check column types in events and cameras
    cols = await conn.fetch("""
        SELECT table_name, column_name, udt_name 
        FROM information_schema.columns 
        WHERE table_schema = 'public' 
          AND table_name IN ('cameras', 'events') 
          AND column_name IN ('geom', 'metadata');
    """)
    print("\nSPATIAL & JSONB COLUMNS:")
    for c in cols:
        print(f"  {c['table_name']}.{c['column_name']} ({c['udt_name']})")

    await conn.close()

if __name__ == "__main__":
    asyncio.run(inspect())
