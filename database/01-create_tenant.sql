-- Helper function for application-side tenant DB creation.
-- Application code (auth_service._create_tenant_database) drives this;
-- the SQL function below is kept for ops convenience.

CREATE OR REPLACE FUNCTION create_tenant_database(user_id INT)
RETURNS TEXT AS $$
DECLARE
    db_name TEXT;
BEGIN
    db_name := 'tenant_' || user_id;
    EXECUTE format('CREATE DATABASE %I TEMPLATE tenant_template', db_name);
    RETURN db_name;
END;
$$ LANGUAGE plpgsql;
