-- Supabase exposes public through its Data API. Only the database owner and
-- explicitly provisioned server roles may use our ledger and queue objects.
DO $$
DECLARE obj record; role_name text;
BEGIN
  FOR obj IN SELECT c.relname,c.relkind FROM pg_class c
    JOIN pg_namespace n ON n.oid=c.relnamespace
    WHERE n.nspname=current_schema() AND c.relkind IN ('r','p','S')
      AND (c.relname LIKE 'ci\_%' ESCAPE '\' OR c.relname LIKE 'procrastinate\_%' ESCAPE '\')
  LOOP
    IF obj.relkind <> 'S' THEN
      EXECUTE format('ALTER TABLE %I.%I ENABLE ROW LEVEL SECURITY',current_schema(),obj.relname);
    END IF;
    EXECUTE format('REVOKE ALL ON %s %I.%I FROM PUBLIC',
      CASE WHEN obj.relkind='S' THEN 'SEQUENCE' ELSE 'TABLE' END,current_schema(),obj.relname);
    FOR role_name IN SELECT rolname FROM pg_roles WHERE rolname IN ('anon','authenticated','service_role') LOOP
      EXECUTE format('REVOKE ALL ON %s %I.%I FROM %I',
        CASE WHEN obj.relkind='S' THEN 'SEQUENCE' ELSE 'TABLE' END,current_schema(),obj.relname,role_name);
    END LOOP;
  END LOOP;
  FOR obj IN SELECT p.oid::regprocedure AS signature FROM pg_proc p
    JOIN pg_namespace n ON n.oid=p.pronamespace
    WHERE n.nspname=current_schema() AND p.proname LIKE 'procrastinate\_%' ESCAPE '\'
  LOOP
    EXECUTE format('REVOKE EXECUTE ON FUNCTION %s FROM PUBLIC',obj.signature);
    FOR role_name IN SELECT rolname FROM pg_roles WHERE rolname IN ('anon','authenticated','service_role') LOOP
      EXECUTE format('REVOKE EXECUTE ON FUNCTION %s FROM %I',obj.signature,role_name);
    END LOOP;
  END LOOP;
END $$;
