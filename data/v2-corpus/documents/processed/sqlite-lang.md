# SQLite SQL 语言概述

Small. Fast. Reliable.Choose any three.

- Home
- Menu
- About
- Documentation
- Download
- License
- Support
- Purchase
-  Search

- About
- Documentation
- Download
- Support
- Purchase

    Search Documentation Search Changelog

# SQL As Understood By SQLite
 SQLite understands most of the standard SQL language. But it does omit some features while at the same time adding a few features of its own. This document attempts to describe precisely what parts of the SQL language SQLite does and does not support. A list of SQL keywords is also provided. The SQL language syntax is described by syntax diagrams. The following syntax documentation topics are available:

 |
- aggregate functions

- ALTER TABLE

- ANALYZE

- ATTACH DATABASE

- BEGIN TRANSACTION

- comment

- COMMIT TRANSACTION

- core functions

- CREATE INDEX

- CREATE TABLE

- CREATE TRIGGER

- CREATE VIEW

- CREATE VIRTUAL TABLE

- date and time functions

- DELETE

- DETACH DATABASE

- DROP INDEX

- DROP TABLE

- DROP TRIGGER

- DROP VIEW

- END TRANSACTION

- EXPLAIN

- expression

- INDEXED BY

- INSERT

- JSON functions

- keywords

- math functions

- ON CONFLICT clause

- PRAGMA

- REINDEX

- RELEASE SAVEPOINT

- REPLACE

- RETURNING clause

- ROLLBACK TRANSACTION

- SAVEPOINT

- SELECT

- UPDATE

- UPSERT

- VACUUM

- window functions

- WITH clause

 The routines sqlite3_prepare_v2(), sqlite3_prepare(), sqlite3_prepare16(), sqlite3_prepare16_v2(), sqlite3_exec(), and sqlite3_get_table() accept an SQL statement list (sql-stmt-list) which is a semicolon-separated list of statements.
 sql-stmt-list:
       sql-stmt         ;

 Each SQL statement in the statement list is an instance of the following:
 sql-stmt:
      EXPLAIN    QUERY    PLAN          alter-table-stmt       analyze-stmt       attach-stmt       begin-stmt       commit-stmt       create-index-stmt       create-table-stmt       create-trigger-stmt       create-view-stmt       create-virtual-table-stmt       delete-stmt       delete-stmt-limited       detach-stmt       drop-index-stmt       drop-table-stmt       drop-trigger-stmt       drop-view-stmt       insert-stmt       pragma-stmt       reindex-stmt       release-stmt       rollback-stmt       savepoint-stmt       select-stmt       update-stmt       update-stmt-limited       vacuum-stmt

 This page was last updated on 2024-04-01 12:41:31Z

# CREATE TABLE

Small. Fast. Reliable.Choose any three.

- Home
- Menu
- About
- Documentation
- Download
- License
- Support
- Purchase
-  Search

- About
- Documentation
- Download
- Support
- Purchase

    Search Documentation Search Changelog

     CREATE TABLE
  Table Of Contents 1. Syntax
 2. The CREATE TABLE command
 2.1. CREATE TABLE ... AS SELECT Statements
 3. Column Definitions
 3.1. Column Data Types
 3.2. The DEFAULT clause
 3.3. The COLLATE clause
 3.4. The GENERATED ALWAYS AS clause
 3.5. The PRIMARY KEY
 3.6. UNIQUE constraints
 3.7. CHECK constraints
 3.8. NOT NULL constraints
 4. Constraint enforcement
 4.1. Response to constraint violations
 5. ROWIDs and the INTEGER PRIMARY KEY

# 1. Syntax
 create-table-stmt: hide
       CREATE  TEMP  TEMPORARY  TABLE              IF    NOT    EXISTS         schema-name    .    table-name         (    column-def  table-constraint    ,  )    table-options  ,                     AS    select-stmt
 column-def: show
       column-name      type-name    column-constraint
 column-constraint: show
           CONSTRAINT    name       PRIMARY    KEY    DESC      conflict-clause      AUTOINCREMENT               ASC       NOT    NULL    conflict-clause       UNIQUE    conflict-clause       CHECK    (    expr    )       DEFAULT      (    expr    )       literal-value       signed-number       COLLATE    collation-name       foreign-key-clause       GENERATED    ALWAYS    AS    (    expr    )          VIRTUAL       STORED
 conflict-clause: show
         ON    CONFLICT    ROLLBACK  ABORT  FAIL  IGNORE  REPLACE

 expr: show
       literal-value     bind-parameter       schema-name    .    table-name    .    column-name             unary-operator    expr       expr    binary-operator    expr       function-name    (    function-arguments    )    filter-clause      over-clause             (    expr    )       ,     CAST    (    expr    AS    type-name    )       expr    COLLATE    collation-name       expr    NOT    LIKE  GLOB  REGEXP  MATCH  expr  expr    ESCAPE    expr                                  expr    ISNULL       NOTNULL  NOT    NULL             expr    IS    NOT      DISTINCT    FROM    expr         expr    NOT    BETWEEN    expr    AND    expr        expr    NOT    IN    (    select-stmt    )         expr     ,     schema-name    .    table-function    (    expr    )     table-name       ,           NOT    EXISTS    (    select-stmt    )           CASE    expr    WHEN    expr    THEN    expr    ELSE    expr    END            raise-function
 filter-clause: show
       FILTER    (    WHERE    expr    )

 function-arguments: show
         DISTINCT        expr         ,      *            ORDER    BY    ordering-term  ,
 ordering-term: show
       expr    COLLATE    collation-name         DESC    ASC          NULLS    FIRST    NULLS    LAST

 over-clause: show
       OVER    window-name    (    base-window-name  PARTITION    BY    expr  ,              ORDER    BY    ordering-term  ,            frame-spec    )
 frame-spec: show
       GROUPS     BETWEEN    UNBOUNDED    PRECEDING    AND    UNBOUNDED    FOLLOWING     RANGE       ROWS       UNBOUNDED    PRECEDING     expr    PRECEDING       CURRENT    ROW       expr    PRECEDING       CURRENT    ROW       expr    FOLLOWING         expr    PRECEDING     CURRENT    ROW       expr    FOLLOWING       EXCLUDE    CURRENT    ROW     EXCLUDE    GROUP     EXCLUDE    TIES     EXCLUDE    NO    OTHERS

 ordering-term: show
       expr    COLLATE    collation-name         DESC    ASC          NULLS    FIRST    NULLS    LAST

 raise-function: show
       RAISE    (    ROLLBACK    ,    expr    )       IGNORE     ABORT     FAIL

 foreign-key-clause: show
       REFERENCES    foreign-table    (    column-name    )  ,     ON    DELETE    SET    NULL  UPDATE     SET    DEFAULT     CASCADE     RESTRICT     NO    ACTION     MATCH    name                        NOT    DEFERRABLE    INITIALLY    DEFERRED  INITIALLY    IMMEDIATE

 literal-value: show
       CURRENT_TIMESTAMP       numeric-literal     string-literal       blob-literal       NULL       TRUE       FALSE       CURRENT_TIME       CURRENT_DATE

 signed-number: show
       +    numeric-literal       -

 type-name: show
       name    (    signed-number    ,    signed-number    )       (    signed-number    )
 signed-number: show
       +    numeric-literal       -

 select-stmt: show
        WITH  RECURSIVE      common-table-expression       ,              SELECT    DISTINCT    result-column  ,        ALL       FROM    table-or-subquery  join-clause  ,                  WHERE    expr           GROUP    BY    expr    HAVING    expr  ,                   WINDOW    window-name    AS    window-defn  ,                    VALUES    (    expr    )     ,  ,          compound-operator      select-core  ORDER    BY  LIMIT    expr    ordering-term  ,                  OFFSET    expr    ,    expr
 common-table-expression: show
       table-name      (      column-name    )    AS  NOT  MATERIALIZED   (    select-stmt    )     ,

 compound-operator: show
         UNION  UNION  INTERSECT  EXCEPT    ALL

 expr: show
       literal-value     bind-parameter       schema-name    .    table-name    .    column-name             unary-operator    expr       expr    binary-operator    expr       function-name    (    function-arguments    )    filter-clause      over-clause             (    expr    )       ,     CAST    (    expr    AS    type-name    )       expr    COLLATE    collation-name       expr    NOT    LIKE  GLOB  REGEXP  MATCH  expr  expr    ESCAPE    expr                                  expr    ISNULL       NOTNULL  NOT    NULL             expr    IS    NOT      DISTINCT    FROM    expr         expr    NOT    BETWEEN    expr    AND    expr        expr    NOT    IN    (    select-stmt    )         expr     ,     schema-name    .    table-function    (    expr    )     table-name       ,           NOT    EXISTS    (    select-stmt    )           CASE    expr    WHEN    expr    THEN    expr    ELSE    expr    END            raise-function
 filter-clause: show
       FILTER    (    WHERE    expr    )

 function-arguments: show
         DISTINCT        expr         ,      *            ORDER    BY    ordering-term  ,

 literal-value: show
       CURRENT_TIMESTAMP       numeric-literal     string-literal       blob-literal       NULL       TRUE       FALSE       CURRENT_TIME       CURRENT_DATE

 over-clause: show
       OVER    window-name    (    base-window-name  PARTITION    BY    expr  ,              ORDER    BY    ordering-term  ,            frame-spec    )
 frame-spec: show
       GROUPS     BETWEEN    UNBOUNDED    PRECEDING    AND    UNBOUNDED    FOLLOWING     RANGE       ROWS       UNBOUNDED    PRECEDING     expr    PRECEDING       CURRENT    ROW       expr    PRECEDING       CURRENT    ROW       expr    FOLLOWING         expr    PRECEDING     CURRENT    ROW       expr    FOLLOWING       EXCLUDE    CURRENT    ROW     EXCLUDE    GROUP     EXCLUDE    TIES     EXCLUDE    NO    OTHERS

 raise-function: show
       RAISE    (    ROLLBACK    ,    expr    )       IGNORE     ABORT     FAIL

 type-name: show
       name    (    signed-number    ,    signed-number    )       (    signed-number    )
 signed-number: show
       +    numeric-literal       -

 join-clause: show
       table-or-subquery    join-operator    table-or-subquery    join-constraint
 join-constraint: show
       USING    (    column-name    )       ,       ON    expr

 join-operator: show
       NATURAL      LEFT    OUTER      JOIN     ,             RIGHT      FULL     INNER       CROSS

 ordering-term: show
       expr    COLLATE    collation-name         DESC    ASC          NULLS    FIRST    NULLS    LAST

 result-column: show
       expr    AS    column-alias               *       table-name    .    *

 table-or-subquery: show
       schema-name    .    table-name    AS    table-alias       INDEXED    BY    index-name  NOT    INDEXED          table-function-name    (    expr    )    ,             AS    table-alias            (    select-stmt    )          (    table-or-subquery    )       ,       join-clause

 window-defn: show
       (    base-window-name  PARTITION    BY    expr  ,              ORDER    BY    ordering-term  ,            frame-spec    )
 frame-spec: show
       GROUPS     BETWEEN    UNBOUNDED    PRECEDING    AND    UNBOUNDED    FOLLOWING     RANGE       ROWS       UNBOUNDED    PRECEDING     expr    PRECEDING       CURRENT    ROW       expr    PRECEDING       CURRENT    ROW       expr    FOLLOWING         expr    PRECEDING     CURRENT    ROW       expr    FOLLOWING       EXCLUDE    CURRENT    ROW     EXCLUDE    GROUP     EXCLUDE    TIES     EXCLUDE    NO    OTHERS

 table-constraint: show
       CONSTRAINT    name  PRIMARY    KEY    (    indexed-column    AUTOINCREMENT    )  UNIQUE    (    indexed-column    )    conflict-clause                   ,       CHECK    (    expr    )       FOREIGN    KEY    (    column-name    )    foreign-key-clause       ,
 conflict-clause: show
         ON    CONFLICT    ROLLBACK  ABORT  FAIL  IGNORE  REPLACE

 expr: show
       literal-value     bind-parameter       schema-name    .    table-name    .    column-name             unary-operator    expr       expr    binary-operator    expr       function-name    (    function-arguments    )    filter-clause      over-clause             (    expr    )       ,     CAST    (    expr    AS    type-name    )       expr    COLLATE    collation-name       expr    NOT    LIKE  GLOB  REGEXP  MATCH  expr  expr    ESCAPE    expr                                  expr    ISNULL       NOTNULL  NOT    NULL             expr    IS    NOT      DISTINCT    FROM    expr         expr    NOT    BETWEEN    expr    AND    expr        expr    NOT    IN    (    select-stmt    )         expr     ,     schema-name    .    table-function    (    expr    )     table-name       ,           NOT    EXISTS    (    select-stmt    )           CASE    expr    WHEN    expr    THEN    expr    ELSE    expr    END            raise-function
 filter-clause: show
       FILTER    (    WHERE    expr    )

 function-arguments: show
         DISTINCT        expr         ,      *            ORDER    BY    ordering-term  ,
 ordering-term: show
       expr    COLLATE    collation-name         DESC    ASC          NULLS    FIRST    NULLS    LAST

 literal-value: show
       CURRENT_TIMESTAMP       numeric-literal     string-literal       blob-literal       NULL       TRUE       FALSE       CURRENT_TIME       CURRENT_DATE

 over-clause: show
       OVER    window-name    (    base-window-name  PARTITION    BY    expr  ,              ORDER    BY    ordering-term  ,            frame-spec    )
 frame-spec: show
       GROUPS     BETWEEN    UNBOUNDED    PRECEDING    AND    UNBOUNDED    FOLLOWING     RANGE       ROWS       UNBOUNDED    PRECEDING     expr    PRECEDING       CURRENT    ROW       expr    PRECEDING       CURRENT    ROW       expr    FOLLOWING         expr    PRECEDING     CURRENT    ROW       expr    FOLLOWING       EXCLUDE    CURRENT    ROW     EXCLUDE    GROUP     EXCLUDE    TIES     EXCLUDE    NO    OTHERS

 ordering-term: show
       expr    COLLATE    collation-name         DESC    ASC          NULLS    FIRST    NULLS    LAST

 raise-function: show
       RAISE    (    ROLLBACK    ,    expr    )       IGNORE     ABORT     FAIL

 type-name: show
       name    (    signed-number    ,    signed-number    )       (    signed-number    )
 signed-number: show
       +    numeric-literal       -

 foreign-key-clause: show
       REFERENCES    foreign-table    (    column-name    )  ,     ON    DELETE    SET    NULL  UPDATE     SET    DEFAULT     CASCADE     RESTRICT     NO    ACTION     MATCH    name                        NOT    DEFERRABLE    INITIALLY    DEFERRED  INITIALLY    IMMEDIATE

 indexed-column: show
       column-name    COLLATE    collation-name      DESC         expr          ASC

 table-options: show
       WITHOUT    ROWID      STRICT      ,

# 2. The CREATE TABLE command
 The "CREATE TABLE" command is used to create a new table in an SQLite database. A CREATE TABLE command specifies the following attributes of the new table:

- The name of the new table.
-  The database in which the new table is created. Tables may be created in the main database, the temp database, or in any attached database.
-  The name of each column in the table.
-  The declared type of each column in the table.
-  A default value or expression for each column in the table.
-  A default collation sequence to use with each column.
-  An optional PRIMARY KEY for the table. Both single column and composite (multiple column) primary keys are supported.
-  Zero or more constraints on the table content. SQLite supports UNIQUE, NOT NULL, CHECK and FOREIGN KEY constraints.
-  Optionally, a generated column constraint.
-  Whether the table is a WITHOUT ROWID table.
-  Whether the table is subject to strict type checking.
 Every CREATE TABLE statement must specify a name for the new table. Table names that begin with "sqlite_" are reserved for internal use. It is an error to attempt to create a table with a name that starts with "sqlite_".
 If a schema-name is specified, it must be either "main", "temp", or the name of an attached database. In this case the new table is created in the named database. If the "TEMP" or "TEMPORARY" keyword occurs between the "CREATE" and "TABLE" then the new table is created in the temp database. It is an error to specify both a schema-name and the TEMP or TEMPORARY keyword, unless the schema-name is "temp". If no schema name is specified and the TEMP keyword is not present then the table is created in the main database.
 It is usually an error to attempt to create a new table in a database that already contains a table, index or view of the same name. However, if the "IF NOT EXISTS" clause is specified as part of the CREATE TABLE statement and a table or view of the same name already exists, the CREATE TABLE command simply has no effect (and no error message is returned). An error is still returned if the table cannot be created because of an existing index, even if the "IF NOT EXISTS" clause is specified.
It is not an error to create a table that has the same name as an existing trigger.
Tables are removed using the DROP TABLE statement.

## 2.1. CREATE TABLE ... AS SELECT Statements
 A "CREATE TABLE ... AS SELECT" statement creates and populates a database table based on the results of a SELECT statement. The table has the same number of columns as the SELECT statement returns. The name of each column is the same as the name of the corresponding column in the result set of the SELECT statement. The declared type of each column is determined by the expression affinity of the corresponding expression in the result set of the SELECT statement, as follows:

Expression Affinity Column Declared Type
 | TEXT  | "TEXT"
 | NUMERIC  | "NUM"
 | INTEGER  | "INT"
 | REAL  | "REAL"
 | BLOB (a.k.a "NONE")  | "" (empty string)
 A table created using CREATE TABLE AS has no PRIMARY KEY and no constraints of any kind. The default value of each column is NULL. The default collation sequence for each column of the new table is BINARY.
Tables created using CREATE TABLE AS are initially populated with the rows of data returned by the SELECT statement. Rows are assigned contiguously ascending rowid values, starting with 1, in the order that they are returned by the SELECT statement.
# 3. Column Definitions
 Unless it is a CREATE TABLE ... AS SELECT statement, a CREATE TABLE includes one or more column definitions, optionally followed by a list of table constraints. Each column definition consists of the name of the column, optionally followed by the declared type of the column, then one or more optional column constraints. Included in the definition of "column constraints" for the purposes of the previous statement are the COLLATE and DEFAULT clauses, even though these are not really constraints in the sense that they do not restrict the data that the table may contain. The other constraints - NOT NULL, CHECK, UNIQUE, PRIMARY KEY and FOREIGN KEY constraints - impose restrictions on the table data.
The number of columns in a table is limited by the SQLITE_MAX_COLUMN compile-time parameter. A single row of a table cannot store more than SQLITE_MAX_LENGTH bytes of data. Both of these limits can be lowered at runtime using the sqlite3_limit() C/C++ interface.

## 3.1. Column Data Types
 Unlike most SQL databases, SQLite does not restrict the type of data that may be inserted into a column based on the columns declared type. Instead, SQLite uses dynamic typing. The declared type of a column is used to determine the affinity of the column only.
## 3.2. The DEFAULT clause
 The DEFAULT clause specifies a default value to use for the column if no value is explicitly provided by the user when doing an INSERT. If there is no explicit DEFAULT clause attached to a column definition, then the default value of the column is NULL. An explicit DEFAULT clause may specify that the default value is NULL, a string constant, a blob constant, a signed-number, or any constant expression enclosed in parentheses. A default value may also be one of the special case-independent keywords CURRENT_TIME, CURRENT_DATE or CURRENT_TIMESTAMP. For the purposes of the DEFAULT clause, an expression is considered constant if it contains no sub-queries, column or table references, bound parameters, or string literals enclosed in double-quotes instead of single-quotes.
Each time a row is inserted into the table by an INSERT statement that does not provide explicit values for all table columns the values stored in the new row are determined by their default values, as follows:

- If the default value of the column is a constant NULL, text, blob or signed-number value, then that value is used directly in the new row.
- If the default value of a column is an expression in parentheses, then the expression is evaluated once for each row inserted and the results used in the new row.
- If the default value of a column is CURRENT_TIME, CURRENT_DATE or CURRENT_TIMESTAMP, then the value used in the new row is a text representation of the current UTC date and/or time. For CURRENT_TIME, the format of the value is "HH:MM:SS". For CURRENT_DATE, "YYYY-MM-DD". The format for CURRENT_TIMESTAMP is "YYYY-MM-DD HH:MM:SS".

## 3.3. The COLLATE clause
 The COLLATE clause specifies the name of a collating sequence to use as the default collation sequence for the column. If no COLLATE clause is specified, the default collation sequence is BINARY.
## 3.4. The GENERATED ALWAYS AS clause
 A column that includes a GENERATED ALWAYS AS clause is a generated column. Generated columns are supported beginning with SQLite version 3.31.0 (2020-01-22). See the separate documentation for details on the capabilities and limitations of generated columns.
## 3.5. The PRIMARY KEY
 Each table in SQLite may have at most one PRIMARY KEY. If the keywords PRIMARY KEY are added to a column definition, then the primary key for the table consists of that single column. Or, if a PRIMARY KEY clause is specified as a table-constraint, then the primary key of the table consists of the list of columns specified as part of the PRIMARY KEY clause. The PRIMARY KEY clause must contain only column names — the use of expressions in an indexed-column of a PRIMARY KEY is not supported. An error is raised if more than one PRIMARY KEY clause appears in a CREATE TABLE statement. The PRIMARY KEY is optional for ordinary tables but is required for WITHOUT ROWID tables.
If a table has a single column primary key and the declared type of that column is "INTEGER" and the table is not a WITHOUT ROWID table, then the column is known as an INTEGER PRIMARY KEY. See below for a description of the special properties and behaviors associated with an INTEGER PRIMARY KEY.
Each row in a table with a primary key must have a unique combination of values in its primary key columns. For the purposes of determining the uniqueness of primary key values, NULL values are considered distinct from all other values, including other NULLs. If an INSERT or UPDATE statement attempts to modify the table content so that two or more rows have identical primary key values, that is a constraint violation.
 According to the SQL standard, PRIMARY KEY should always imply NOT NULL. Unfortunately, due to a bug in some early versions, this is not the case in SQLite. Unless the column is an INTEGER PRIMARY KEY or the table is a WITHOUT ROWID table or a STRICT table or the column is declared NOT NULL, SQLite allows NULL values in a PRIMARY KEY column. SQLite could be fixed to conform to the standard, but doing so might break legacy applications. Hence, it has been decided to merely document the fact that SQLite allows NULLs in most PRIMARY KEY columns.
## 3.6. UNIQUE constraints
 A UNIQUE constraint is similar to a PRIMARY KEY constraint, except that a single table may have any number of UNIQUE constraints. For each UNIQUE constraint on the table, each row must contain a unique combination of values in the columns identified by the UNIQUE constraint. For the purposes of UNIQUE constraints, NULL values are considered distinct from all other values, including other NULLs. As with PRIMARY KEYs, a UNIQUE table-constraint clause must contain only column names — the use of expressions in an indexed-column of a UNIQUE table-constraint is not supported.
In most cases, UNIQUE and PRIMARY KEY constraints are implemented by creating a unique index in the database. (The exceptions are INTEGER PRIMARY KEY and PRIMARY KEYs on WITHOUT ROWID tables.) Hence, the following schemas are logically equivalent:

1. CREATE TABLE t1(a, b UNIQUE);
1. CREATE TABLE t1(a, b PRIMARY KEY);
1. CREATE TABLE t1(a, b); CREATE UNIQUE INDEX t1b ON t1(b);

## 3.7. CHECK constraints
 A CHECK constraint may be attached to a column definition or specified as a table constraint. In practice it makes no difference. Each time a new row is inserted into the table or an existing row is updated, the expression associated with each CHECK constraint is evaluated and cast to a NUMERIC value in the same way as a CAST expression. If the result is zero (integer value 0 or real value 0.0), then a constraint violation has occurred. If the CHECK expression evaluates to NULL, or any other non-zero value, it is not a constraint violation. The expression of a CHECK constraint may not contain a subquery.
CHECK constraints are only verified when the table is written, not when it is read. Furthermore, verification of CHECK constraints can be temporarily disabled using the "PRAGMA ignore_check_constraints=ON;" statement. Hence, it is possible that a query might produce results that violate the CHECK constraints.
## 3.8. NOT NULL constraints
 A NOT NULL constraint may only be attached to a column definition, not specified as a table constraint. Not surprisingly, a NOT NULL constraint dictates that the associated column may not contain a NULL value. Attempting to set the column value to NULL when inserting a new row or updating an existing one causes a constraint violation. NOT NULL constraints are not verified during queries, so a query of a column might produce a NULL value even though the column is marked as NOT NULL, if the database file is corrupt.
# 4. Constraint enforcement
 Constraints are checked during INSERT and UPDATE and by PRAGMA integrity_check and PRAGMA quick_check and sometimes by ALTER TABLE. Queries and DELETE statements do not normally verify constraints. Hence, if a database file has been corrupted (perhaps by an external program making direct changes to the database file without going through the SQLite library) a query might return data that violates a constraint. For example:
```
CREATE TABLE t1(x INT CHECK( x>3 ));
/* Insert a row with X less than 3 by directly writing into the
** database file using an external program */
PRAGMA integrity_check;  -- Reports row with x less than 3 as corrupt
INSERT INTO t1(x) VALUES(2);  -- Fails with SQLITE_CORRUPT
SELECT x FROM t1;  -- Returns an integer less than 3 in spite of the CHECK constraint
```
 Enforcement of CHECK constraints can be temporarily disabled using the PRAGMA ignore_check_constraints=ON; statement.
## 4.1. Response to constraint violations
 The response to a constraint violation is determined by the constraint conflict resolution algorithm. Each PRIMARY KEY, UNIQUE, NOT NULL and CHECK constraint has a default conflict resolution algorithm. PRIMARY KEY, UNIQUE and NOT NULL constraints may be explicitly assigned another default conflict resolution algorithm by including a conflict-clause in their definitions. Or, if a constraint definition does not include a conflict-clause, the default conflict resolution algorithm is ABORT. The conflict resolution algorithm for CHECK constraints is always ABORT. (For historical compatibility only, table CHECK constraints are allowed to have a conflict resolution clause, but that has no effect.) Different constraints within the same table may have different default conflict resolution algorithms. See the section titled ON CONFLICT for additional information.
# 5. ROWIDs and the INTEGER PRIMARY KEY
 Except for WITHOUT ROWID tables, all rows within SQLite tables have a 64-bit signed integer key that uniquely identifies the row within its table. This integer is usually called the "rowid". The rowid value can be accessed using one of the special case-independent names "rowid", "oid", or "_rowid_" in place of a column name. If a table contains a user defined column named "rowid", "oid" or "_rowid_", then that name always refers the explicitly declared column and cannot be used to retrieve the integer rowid value.
The rowid (and "oid" and "_rowid_") is omitted in WITHOUT ROWID tables. WITHOUT ROWID tables are only available in SQLite version 3.8.2 (2013-12-06) and later. A table that lacks the WITHOUT ROWID clause is called a "rowid table".
The data for rowid tables is stored as a B-Tree structure containing one entry for each table row, using the rowid value as the key. This means that retrieving or sorting records by rowid is fast. Searching for a record with a specific rowid, or for all records with rowids within a specified range is around twice as fast as a similar search made by specifying any other PRIMARY KEY or indexed value.
 With one exception noted below, if a rowid table has a primary key that consists of a single column and the declared type of that column is "INTEGER" in any mixture of upper and lower case, then the column becomes an alias for the rowid. Such a column is usually referred to as an "integer primary key". A PRIMARY KEY column only becomes an integer primary key if the declared type name is exactly "INTEGER". Other integer type names like "INT" or "BIGINT" or "SHORT INTEGER" or "UNSIGNED INTEGER" causes the primary key column to behave as an ordinary table column with integer affinity and a unique index, not as an alias for the rowid.
 The exception mentioned above is that if the declaration of a column with declared type "INTEGER" includes an "PRIMARY KEY DESC" clause, it does not become an alias for the rowid and is not classified as an integer primary key. This quirk is not by design. It is due to a bug in early versions of SQLite. But fixing the bug could result in backwards incompatibilities. Hence, the original behavior has been retained (and documented) because odd behavior in a corner case is far better than a compatibility break. This means that the following three table declarations all cause the column "x" to be an alias for the rowid (an integer primary key):

-
```
CREATE TABLE t(x INTEGER PRIMARY KEY ASC, y, z);
```

-
```
CREATE TABLE t(x INTEGER, y, z, PRIMARY KEY(x ASC));
```

-
```
CREATE TABLE t(x INTEGER, y, z, PRIMARY KEY(x DESC));
```

 But the following declaration does not result in "x" being an alias for the rowid:

-
```
CREATE TABLE t(x INTEGER PRIMARY KEY DESC, y, z);
```

 Rowid values may be modified using an UPDATE statement in the same way as any other column value can, either using one of the built-in aliases ("rowid", "oid" or "_rowid_") or by using an alias created by an integer primary key. Similarly, an INSERT statement may provide a value to use as the rowid for each row inserted. Unlike normal SQLite columns, an integer primary key or rowid column must contain integer values. Integer primary key or rowid columns are not able to hold floating point values, strings, BLOBs, or NULLs.
If an UPDATE statement attempts to set an integer primary key or rowid column to a NULL or blob value, or to a string or real value that cannot be losslessly converted to an integer, a "datatype mismatch" error occurs and the statement is aborted. If an INSERT statement attempts to insert a blob value, or a string or real value that cannot be losslessly converted to an integer into an integer primary key or rowid column, a "datatype mismatch" error occurs and the statement is aborted.
If an INSERT statement attempts to insert a NULL value into a rowid or integer primary key column, the system chooses an integer value to use as the rowid automatically. A detailed description of how this is done is provided separately.
 The parent key of a foreign key constraint is not allowed to use the rowid. The parent key must use named columns only.
 This page was last updated on 2025-04-30 20:02:34Z

# SELECT

Small. Fast. Reliable.Choose any three.

- Home
- Menu
- About
- Documentation
- Download
- License
- Support
- Purchase
-  Search

- About
- Documentation
- Download
- Support
- Purchase

    Search Documentation Search Changelog

     SELECT
  Table Of Contents 1. Overview
 2. Simple Select Processing
 2.1. Determination of input data (FROM clause processing)
 2.2. Special handling of CROSS JOIN.
 2.3. WHERE clause filtering.
 2.4. Generation of the set of result rows
 2.5. Bare columns in an aggregate query
 2.5.1. Notes
 2.6. Removal of duplicate rows (DISTINCT processing)
 3. Compound Select Statements
 4. The ORDER BY clause
 5. The LIMIT clause
 6. The VALUES clause
 7. The WITH Clause
 8. Table-valued Functions In The FROM Clause
 9. Deviations From Standard SQL
 9.1. Strange JOIN names
 9.2. Flexible join syntax
 9.3. Precedence of comma-joins and CROSS JOIN

# 1. Overview
 select-stmt: hide
        WITH  RECURSIVE      common-table-expression       ,              SELECT    DISTINCT    result-column  ,        ALL       FROM    table-or-subquery  join-clause  ,                  WHERE    expr           GROUP    BY    expr    HAVING    expr  ,                   WINDOW    window-name    AS    window-defn  ,                    VALUES    (    expr    )     ,  ,          compound-operator      select-core  ORDER    BY  LIMIT    expr    ordering-term  ,                  OFFSET    expr    ,    expr
 common-table-expression: show
       table-name      (      column-name    )    AS  NOT  MATERIALIZED   (    select-stmt    )     ,

 compound-operator: show
         UNION  UNION  INTERSECT  EXCEPT    ALL

 expr: show
       literal-value     bind-parameter       schema-name    .    table-name    .    column-name             unary-operator    expr       expr    binary-operator    expr       function-name    (    function-arguments    )    filter-clause      over-clause             (    expr    )       ,     CAST    (    expr    AS    type-name    )       expr    COLLATE    collation-name       expr    NOT    LIKE  GLOB  REGEXP  MATCH  expr  expr    ESCAPE    expr                                  expr    ISNULL       NOTNULL  NOT    NULL             expr    IS    NOT      DISTINCT    FROM    expr         expr    NOT    BETWEEN    expr    AND    expr        expr    NOT    IN    (    select-stmt    )         expr     ,     schema-name    .    table-function    (    expr    )     table-name       ,           NOT    EXISTS    (    select-stmt    )           CASE    expr    WHEN    expr    THEN    expr    ELSE    expr    END            raise-function
 filter-clause: show
       FILTER    (    WHERE    expr    )

 function-arguments: show
         DISTINCT        expr         ,      *            ORDER    BY    ordering-term  ,

 literal-value: show
       CURRENT_TIMESTAMP       numeric-literal     string-literal       blob-literal       NULL       TRUE       FALSE       CURRENT_TIME       CURRENT_DATE

 over-clause: show
       OVER    window-name    (    base-window-name  PARTITION    BY    expr  ,              ORDER    BY    ordering-term  ,            frame-spec    )
 frame-spec: show
       GROUPS     BETWEEN    UNBOUNDED    PRECEDING    AND    UNBOUNDED    FOLLOWING     RANGE       ROWS       UNBOUNDED    PRECEDING     expr    PRECEDING       CURRENT    ROW       expr    PRECEDING       CURRENT    ROW       expr    FOLLOWING         expr    PRECEDING     CURRENT    ROW       expr    FOLLOWING       EXCLUDE    CURRENT    ROW     EXCLUDE    GROUP     EXCLUDE    TIES     EXCLUDE    NO    OTHERS

 raise-function: show
       RAISE    (    ROLLBACK    ,    expr    )       IGNORE     ABORT     FAIL

 type-name: show
       name    (    signed-number    ,    signed-number    )       (    signed-number    )
 signed-number: show
       +    numeric-literal       -

 join-clause: show
       table-or-subquery    join-operator    table-or-subquery    join-constraint
 join-constraint: show
       USING    (    column-name    )       ,       ON    expr

 join-operator: show
       NATURAL      LEFT    OUTER      JOIN     ,             RIGHT      FULL     INNER       CROSS

 ordering-term: show
       expr    COLLATE    collation-name         DESC    ASC          NULLS    FIRST    NULLS    LAST

 result-column: show
       expr    AS    column-alias               *       table-name    .    *

 table-or-subquery: show
       schema-name    .    table-name    AS    table-alias       INDEXED    BY    index-name  NOT    INDEXED          table-function-name    (    expr    )    ,             AS    table-alias            (    select-stmt    )          (    table-or-subquery    )       ,       join-clause

 window-defn: show
       (    base-window-name  PARTITION    BY    expr  ,              ORDER    BY    ordering-term  ,            frame-spec    )
 frame-spec: show
       GROUPS     BETWEEN    UNBOUNDED    PRECEDING    AND    UNBOUNDED    FOLLOWING     RANGE       ROWS       UNBOUNDED    PRECEDING     expr    PRECEDING       CURRENT    ROW       expr    PRECEDING       CURRENT    ROW       expr    FOLLOWING         expr    PRECEDING     CURRENT    ROW       expr    FOLLOWING       EXCLUDE    CURRENT    ROW     EXCLUDE    GROUP     EXCLUDE    TIES     EXCLUDE    NO    OTHERS

 The SELECT statement is used to query the database. The result of a SELECT is zero or more rows of data where each row has a fixed number of columns. A SELECT statement does not make any changes to the database.
The "select-stmt" syntax diagram above attempts to show as much of the SELECT statement syntax as possible in a single diagram, because some readers find that helpful. The following "factored-select-stmt" is an alternative syntax diagrams that expresses the same syntax but tries to break the syntax down into smaller chunks. factored-select-stmt: show
       WITH  RECURSIVE      common-table-expression       ,     select-core  ORDER    BY  LIMIT    expr       compound-operator           ordering-term  ,              OFFSET    expr    ,    expr
 common-table-expression: show
       table-name      (      column-name    )    AS  NOT  MATERIALIZED   (    select-stmt    )     ,
 select-stmt: show
        WITH  RECURSIVE      common-table-expression       ,              SELECT    DISTINCT    result-column  ,        ALL       FROM    table-or-subquery  join-clause  ,                  WHERE    expr           GROUP    BY    expr    HAVING    expr  ,                   WINDOW    window-name    AS    window-defn  ,                    VALUES    (    expr    )     ,  ,          compound-operator      select-core  ORDER    BY  LIMIT    expr    ordering-term  ,                  OFFSET    expr    ,    expr
 join-clause: show
       table-or-subquery    join-operator    table-or-subquery    join-constraint
 join-constraint: show
       USING    (    column-name    )       ,       ON    expr

 join-operator: show
       NATURAL      LEFT    OUTER      JOIN     ,             RIGHT      FULL     INNER       CROSS

 result-column: show
       expr    AS    column-alias               *       table-name    .    *

 table-or-subquery: show
       schema-name    .    table-name    AS    table-alias       INDEXED    BY    index-name  NOT    INDEXED          table-function-name    (    expr    )    ,             AS    table-alias            (    select-stmt    )          (    table-or-subquery    )       ,       join-clause

 window-defn: show
       (    base-window-name  PARTITION    BY    expr  ,              ORDER    BY    ordering-term  ,            frame-spec    )
 frame-spec: show
       GROUPS     BETWEEN    UNBOUNDED    PRECEDING    AND    UNBOUNDED    FOLLOWING     RANGE       ROWS       UNBOUNDED    PRECEDING     expr    PRECEDING       CURRENT    ROW       expr    PRECEDING       CURRENT    ROW       expr    FOLLOWING         expr    PRECEDING     CURRENT    ROW       expr    FOLLOWING       EXCLUDE    CURRENT    ROW     EXCLUDE    GROUP     EXCLUDE    TIES     EXCLUDE    NO    OTHERS

 compound-operator: show
         UNION  UNION  INTERSECT  EXCEPT    ALL

 expr: show
       literal-value     bind-parameter       schema-name    .    table-name    .    column-name             unary-operator    expr       expr    binary-operator    expr       function-name    (    function-arguments    )    filter-clause      over-clause             (    expr    )       ,     CAST    (    expr    AS    type-name    )       expr    COLLATE    collation-name       expr    NOT    LIKE  GLOB  REGEXP  MATCH  expr  expr    ESCAPE    expr                                  expr    ISNULL       NOTNULL  NOT    NULL             expr    IS    NOT      DISTINCT    FROM    expr         expr    NOT    BETWEEN    expr    AND    expr        expr    NOT    IN    (    select-stmt    )         expr     ,     schema-name    .    table-function    (    expr    )     table-name       ,           NOT    EXISTS    (    select-stmt    )           CASE    expr    WHEN    expr    THEN    expr    ELSE    expr    END            raise-function
 filter-clause: show
       FILTER    (    WHERE    expr    )

 function-arguments: show
         DISTINCT        expr         ,      *            ORDER    BY    ordering-term  ,

 literal-value: show
       CURRENT_TIMESTAMP       numeric-literal     string-literal       blob-literal       NULL       TRUE       FALSE       CURRENT_TIME       CURRENT_DATE

 over-clause: show
       OVER    window-name    (    base-window-name  PARTITION    BY    expr  ,              ORDER    BY    ordering-term  ,            frame-spec    )
 frame-spec: show
       GROUPS     BETWEEN    UNBOUNDED    PRECEDING    AND    UNBOUNDED    FOLLOWING     RANGE       ROWS       UNBOUNDED    PRECEDING     expr    PRECEDING       CURRENT    ROW       expr    PRECEDING       CURRENT    ROW       expr    FOLLOWING         expr    PRECEDING     CURRENT    ROW       expr    FOLLOWING       EXCLUDE    CURRENT    ROW     EXCLUDE    GROUP     EXCLUDE    TIES     EXCLUDE    NO    OTHERS

 raise-function: show
       RAISE    (    ROLLBACK    ,    expr    )       IGNORE     ABORT     FAIL

 select-stmt: show
        WITH  RECURSIVE      common-table-expression       ,              SELECT    DISTINCT    result-column  ,        ALL       FROM    table-or-subquery  join-clause  ,                  WHERE    expr           GROUP    BY    expr    HAVING    expr  ,                   WINDOW    window-name    AS    window-defn  ,                    VALUES    (    expr    )     ,  ,          compound-operator      select-core  ORDER    BY  LIMIT    expr    ordering-term  ,                  OFFSET    expr    ,    expr
 join-clause: show
       table-or-subquery    join-operator    table-or-subquery    join-constraint
 join-constraint: show
       USING    (    column-name    )       ,       ON    expr

 join-operator: show
       NATURAL      LEFT    OUTER      JOIN     ,             RIGHT      FULL     INNER       CROSS

 result-column: show
       expr    AS    column-alias               *       table-name    .    *

 table-or-subquery: show
       schema-name    .    table-name    AS    table-alias       INDEXED    BY    index-name  NOT    INDEXED          table-function-name    (    expr    )    ,             AS    table-alias            (    select-stmt    )          (    table-or-subquery    )       ,       join-clause

 window-defn: show
       (    base-window-name  PARTITION    BY    expr  ,              ORDER    BY    ordering-term  ,            frame-spec    )
 frame-spec: show
       GROUPS     BETWEEN    UNBOUNDED    PRECEDING    AND    UNBOUNDED    FOLLOWING     RANGE       ROWS       UNBOUNDED    PRECEDING     expr    PRECEDING       CURRENT    ROW       expr    PRECEDING       CURRENT    ROW       expr    FOLLOWING         expr    PRECEDING     CURRENT    ROW       expr    FOLLOWING       EXCLUDE    CURRENT    ROW     EXCLUDE    GROUP     EXCLUDE    TIES     EXCLUDE    NO    OTHERS

 type-name: show
       name    (    signed-number    ,    signed-number    )       (    signed-number    )
 signed-number: show
       +    numeric-literal       -

 ordering-term: show
       expr    COLLATE    collation-name         DESC    ASC          NULLS    FIRST    NULLS    LAST

 select-core: show
       SELECT    DISTINCT    result-column  ,        ALL       FROM    table-or-subquery  join-clause  ,                  WHERE    expr           GROUP    BY    expr    HAVING    expr  ,                   WINDOW    window-name    AS    window-defn  ,                     VALUES    (    expr    )       ,  ,
 join-clause: show
       table-or-subquery    join-operator    table-or-subquery    join-constraint
 join-constraint: show
       USING    (    column-name    )       ,       ON    expr

 join-operator: show
       NATURAL      LEFT    OUTER      JOIN     ,             RIGHT      FULL     INNER       CROSS

 result-column: show
       expr    AS    column-alias               *       table-name    .    *

 table-or-subquery: show
       schema-name    .    table-name    AS    table-alias       INDEXED    BY    index-name  NOT    INDEXED          table-function-name    (    expr    )    ,             AS    table-alias            (    select-stmt    )          (    table-or-subquery    )       ,       join-clause
 select-stmt: show
        WITH  RECURSIVE      common-table-expression       ,              SELECT    DISTINCT    result-column  ,        ALL       FROM    table-or-subquery  join-clause  ,                  WHERE    expr           GROUP    BY    expr    HAVING    expr  ,                   WINDOW    window-name    AS    window-defn  ,                    VALUES    (    expr    )     ,  ,          compound-operator      select-core  ORDER    BY  LIMIT    expr    ordering-term  ,                  OFFSET    expr    ,    expr

 window-defn: show
       (    base-window-name  PARTITION    BY    expr  ,              ORDER    BY    ordering-term  ,            frame-spec    )
 frame-spec: show
       GROUPS     BETWEEN    UNBOUNDED    PRECEDING    AND    UNBOUNDED    FOLLOWING     RANGE       ROWS       UNBOUNDED    PRECEDING     expr    PRECEDING       CURRENT    ROW       expr    PRECEDING       CURRENT    ROW       expr    FOLLOWING         expr    PRECEDING     CURRENT    ROW       expr    FOLLOWING       EXCLUDE    CURRENT    ROW     EXCLUDE    GROUP     EXCLUDE    TIES     EXCLUDE    NO    OTHERS

Note that there are paths through the syntax diagrams that are not allowed in practice. Some examples:

- A VALUES clause can be the first element in a compound SELECT that uses a WITH clause, but a simple SELECT that consists of just a VALUES clause cannot be preceded by a WITH clause.
- The WITH clause must occur on the first SELECT of a compound SELECT. It cannot follow a compound-operator.
 These and other similar syntax restrictions are described in the text.
The SELECT statement is the most complicated command in the SQL language. To make the description easier to follow, some of the passages below describe the way the data returned by a SELECT statement is determined as a series of steps. It is important to keep in mind that this is purely illustrative - in practice neither SQLite nor any other SQL engine is required to follow this or any other specific process.
# 2. Simple Select Processing
 The core of a SELECT statement is a "simple SELECT" shown by the select-core and simple-select-stmt syntax diagrams below. In practice, most SELECT statements are simple SELECT statements. simple-select-stmt: hide
       WITH  RECURSIVE      common-table-expression       ,     select-core  ORDER    BY  LIMIT    expr         ordering-term  ,                OFFSET    expr    ,    expr
 common-table-expression: show
       table-name      (      column-name    )    AS  NOT  MATERIALIZED   (    select-stmt    )     ,
 select-stmt: show
        WITH  RECURSIVE      common-table-expression       ,              SELECT    DISTINCT    result-column  ,        ALL       FROM    table-or-subquery  join-clause  ,                  WHERE    expr           GROUP    BY    expr    HAVING    expr  ,                   WINDOW    window-name    AS    window-defn  ,                    VALUES    (    expr    )     ,  ,          compound-operator      select-core  ORDER    BY  LIMIT    expr    ordering-term  ,                  OFFSET    expr    ,    expr
 compound-operator: show
         UNION  UNION  INTERSECT  EXCEPT    ALL

 join-clause: show
       table-or-subquery    join-operator    table-or-subquery    join-constraint
 join-constraint: show
       USING    (    column-name    )       ,       ON    expr

 join-operator: show
       NATURAL      LEFT    OUTER      JOIN     ,             RIGHT      FULL     INNER       CROSS

 result-column: show
       expr    AS    column-alias               *       table-name    .    *

 table-or-subquery: show
       schema-name    .    table-name    AS    table-alias       INDEXED    BY    index-name  NOT    INDEXED          table-function-name    (    expr    )    ,             AS    table-alias            (    select-stmt    )          (    table-or-subquery    )       ,       join-clause

 window-defn: show
       (    base-window-name  PARTITION    BY    expr  ,              ORDER    BY    ordering-term  ,            frame-spec    )
 frame-spec: show
       GROUPS     BETWEEN    UNBOUNDED    PRECEDING    AND    UNBOUNDED    FOLLOWING     RANGE       ROWS       UNBOUNDED    PRECEDING     expr    PRECEDING       CURRENT    ROW       expr    PRECEDING       CURRENT    ROW       expr    FOLLOWING         expr    PRECEDING     CURRENT    ROW       expr    FOLLOWING       EXCLUDE    CURRENT    ROW     EXCLUDE    GROUP     EXCLUDE    TIES     EXCLUDE    NO    OTHERS

 expr: show
       literal-value     bind-parameter       schema-name    .    table-name    .    column-name             unary-operator    expr       expr    binary-operator    expr       function-name    (    function-arguments    )    filter-clause      over-clause             (    expr    )       ,     CAST    (    expr    AS    type-name    )       expr    COLLATE    collation-name       expr    NOT    LIKE  GLOB  REGEXP  MATCH  expr  expr    ESCAPE    expr                                  expr    ISNULL       NOTNULL  NOT    NULL             expr    IS    NOT      DISTINCT    FROM    expr         expr    NOT    BETWEEN    expr    AND    expr        expr    NOT    IN    (    select-stmt    )         expr     ,     schema-name    .    table-function    (    expr    )     table-name       ,           NOT    EXISTS    (    select-stmt    )           CASE    expr    WHEN    expr    THEN    expr    ELSE    expr    END            raise-function
 filter-clause: show
       FILTER    (    WHERE    expr    )

 function-arguments: show
         DISTINCT        expr         ,      *            ORDER    BY    ordering-term  ,

 literal-value: show
       CURRENT_TIMESTAMP       numeric-literal     string-literal       blob-literal       NULL       TRUE       FALSE       CURRENT_TIME       CURRENT_DATE

 over-clause: show
       OVER    window-name    (    base-window-name  PARTITION    BY    expr  ,              ORDER    BY    ordering-term  ,            frame-spec    )
 frame-spec: show
       GROUPS     BETWEEN    UNBOUNDED    PRECEDING    AND    UNBOUNDED    FOLLOWING     RANGE       ROWS       UNBOUNDED    PRECEDING     expr    PRECEDING       CURRENT    ROW       expr    PRECEDING       CURRENT    ROW       expr    FOLLOWING         expr    PRECEDING     CURRENT    ROW       expr    FOLLOWING       EXCLUDE    CURRENT    ROW     EXCLUDE    GROUP     EXCLUDE    TIES     EXCLUDE    NO    OTHERS

 raise-function: show
       RAISE    (    ROLLBACK    ,    expr    )       IGNORE     ABORT     FAIL

 select-stmt: show
        WITH  RECURSIVE      common-table-expression       ,              SELECT    DISTINCT    result-column  ,        ALL       FROM    table-or-subquery  join-clause  ,                  WHERE    expr           GROUP    BY    expr    HAVING    expr  ,                   WINDOW    window-name    AS    window-defn  ,                    VALUES    (    expr    )     ,  ,          compound-operator      select-core  ORDER    BY  LIMIT    expr    ordering-term  ,                  OFFSET    expr    ,    expr
 compound-operator: show
         UNION  UNION  INTERSECT  EXCEPT    ALL

 join-clause: show
       table-or-subquery    join-operator    table-or-subquery    join-constraint
 join-constraint: show
       USING    (    column-name    )       ,       ON    expr

 join-operator: show
       NATURAL      LEFT    OUTER      JOIN     ,             RIGHT      FULL     INNER       CROSS

 result-column: show
       expr    AS    column-alias               *       table-name    .    *

 table-or-subquery: show
       schema-name    .    table-name    AS    table-alias       INDEXED    BY    index-name  NOT    INDEXED          table-function-name    (    expr    )    ,             AS    table-alias            (    select-stmt    )          (    table-or-subquery    )       ,       join-clause

 window-defn: show
       (    base-window-name  PARTITION    BY    expr  ,              ORDER    BY    ordering-term  ,            frame-spec    )
 frame-spec: show
       GROUPS     BETWEEN    UNBOUNDED    PRECEDING    AND    UNBOUNDED    FOLLOWING     RANGE       ROWS       UNBOUNDED    PRECEDING     expr    PRECEDING       CURRENT    ROW       expr    PRECEDING       CURRENT    ROW       expr    FOLLOWING         expr    PRECEDING     CURRENT    ROW       expr    FOLLOWING       EXCLUDE    CURRENT    ROW     EXCLUDE    GROUP     EXCLUDE    TIES     EXCLUDE    NO    OTHERS

 type-name: show
       name    (    signed-number    ,    signed-number    )       (    signed-number    )
 signed-number: show
       +    numeric-literal       -

 ordering-term: show
       expr    COLLATE    collation-name         DESC    ASC          NULLS    FIRST    NULLS    LAST

 select-core: hide
       SELECT    DISTINCT    result-column  ,        ALL       FROM    table-or-subquery  join-clause  ,                  WHERE    expr           GROUP    BY    expr    HAVING    expr  ,                   WINDOW    window-name    AS    window-defn  ,                     VALUES    (    expr    )       ,  ,
 join-clause: show
       table-or-subquery    join-operator    table-or-subquery    join-constraint
 join-constraint: show
       USING    (    column-name    )       ,       ON    expr

 join-operator: show
       NATURAL      LEFT    OUTER      JOIN     ,             RIGHT      FULL     INNER       CROSS

 result-column: show
       expr    AS    column-alias               *       table-name    .    *

 table-or-subquery: show
       schema-name    .    table-name    AS    table-alias       INDEXED    BY    index-name  NOT    INDEXED          table-function-name    (    expr    )    ,             AS    table-alias            (    select-stmt    )          (    table-or-subquery    )       ,       join-clause
 select-stmt: show
        WITH  RECURSIVE      common-table-expression       ,              SELECT    DISTINCT    result-column  ,        ALL       FROM    table-or-subquery  join-clause  ,                  WHERE    expr           GROUP    BY    expr    HAVING    expr  ,                   WINDOW    window-name    AS    window-defn  ,                    VALUES    (    expr    )     ,  ,          compound-operator      select-core  ORDER    BY  LIMIT    expr    ordering-term  ,                  OFFSET    expr    ,    expr
 compound-operator: show
         UNION  UNION  INTERSECT  EXCEPT    ALL

 window-defn: show
       (    base-window-name  PARTITION    BY    expr  ,              ORDER    BY    ordering-term  ,            frame-spec    )
 frame-spec: show
       GROUPS     BETWEEN    UNBOUNDED    PRECEDING    AND    UNBOUNDED    FOLLOWING     RANGE       ROWS       UNBOUNDED    PRECEDING     expr    PRECEDING       CURRENT    ROW       expr    PRECEDING       CURRENT    ROW       expr    FOLLOWING         expr    PRECEDING     CURRENT    ROW       expr    FOLLOWING       EXCLUDE    CURRENT    ROW     EXCLUDE    GROUP     EXCLUDE    TIES     EXCLUDE    NO    OTHERS

Generating the results of a simple SELECT statement is presented as a four step process in the description below:

1.  FROM clause processing: The input data for the simple SELECT is determined. The input data is either implicitly a single row with 0 columns (if there is no FROM clause) or is determined by the FROM clause.
1.  WHERE clause processing: The input data is filtered using the WHERE clause expression.
1.  GROUP BY, HAVING and result-column expression processing: The set of result rows is computed by aggregating the data according to any GROUP BY clause and calculating the result-set expressions for the rows of the filtered input dataset.
1.  DISTINCT/ALL keyword processing: If the query is a "SELECT DISTINCT" query, duplicate rows are removed from the set of result rows.
 There are two types of simple SELECT statement - aggregate and non-aggregate queries. A simple SELECT statement is an aggregate query if it contains either a GROUP BY clause or one or more aggregate functions in the result-set. Otherwise, if a simple SELECT contains no aggregate functions or a GROUP BY clause, it is a non-aggregate query.
## 2.1. Determination of input data (FROM clause processing)
 The input data used by a simple SELECT query is a set of N rows each M columns wide.
If the FROM clause is omitted from a simple SELECT statement, then the input data is implicitly a single row zero columns wide (i.e. N=1 and M=0).
If a FROM clause is specified, the data on which a simple SELECT query operates comes from the one or more tables or subqueries (SELECT statements in parentheses) specified following the FROM keyword. A subquery specified in the table-or-subquery following the FROM clause in a simple SELECT statement is handled as if it was a table containing the data returned by executing the subquery statement. Each column of the subquery has the collation sequence and affinity of the corresponding expression in the subquery statement.
If there is only a single table or subquery in the FROM clause, then the input data used by the SELECT statement is the contents of the named table. If there is more than one table or subquery in the FROM clause then the contents of all tables and/or subqueries are joined into a single dataset for the simple SELECT statement to operate on. Exactly how the data is combined depends on the specific join-operator and join-constraint used to connect the tables or subqueries together.
All joins in SQLite are based on the cartesian product of the left and right-hand datasets. The columns of the cartesian product dataset are, in order, all the columns of the left-hand dataset followed by all the columns of the right-hand dataset. There is a row in the cartesian product dataset formed by combining each unique combination of a row from the left-hand and right-hand datasets. In other words, if the left-hand dataset consists of Nleft rows of Mleft columns, and the right-hand dataset of Nright rows of Mright columns, then the cartesian product is a dataset of Nleft×Nright rows, each containing Mleft+Mright columns.
If the join-operator is "CROSS JOIN", "INNER JOIN", "JOIN" or a comma (",") and there is no ON or USING clause, then the result of the join is simply the cartesian product of the left and right-hand datasets. If join-operator does have ON or USING clauses, those are handled according to the following bullet points:

-  If there is an ON clause then the ON expression is evaluated for each row of the cartesian product as a boolean expression. Only rows for which the expression evaluates to true are included from the dataset.
-  If there is a USING clause then each of the column names specified must exist in the datasets to both the left and right of the join-operator. For each pair of named columns, the expression "lhs.X = rhs.X" is evaluated for each row of the cartesian product as a boolean expression. Only rows for which all such expressions evaluate to true are included from the result set. When comparing values as a result of a USING clause, the normal rules for handling affinities, collation sequences and NULL values in comparisons apply. The column from the dataset on the left-hand side of the join-operator is considered to be on the left-hand side of the comparison operator (=) for the purposes of collation sequence and affinity precedence.
For each pair of columns identified by a USING clause, the column from the right-hand dataset is omitted from the joined dataset. This is the only difference between a USING clause and its equivalent ON constraint.
-  If the NATURAL keyword is in the join-operator then an implicit USING clause is added to the join-constraints. The implicit USING clause contains each of the column names that appear in both the left and right-hand input datasets. If the left and right-hand input datasets feature no common column names, then the NATURAL keyword has no effect on the results of the join. A USING or ON clause may not be added to a join that specifies the NATURAL keyword.
-  If the join-operator is a "LEFT JOIN" or "LEFT OUTER JOIN", then after the ON or USING filtering clauses have been applied, an extra row is added to the output for each row in the original left-hand input dataset that does not match any row in the right-hand dataset. The added rows contain NULL values in the columns that would normally contain values copied from the right-hand input dataset.
-    If the join-operator is a "RIGHT JOIN" or "RIGHT OUTER JOIN", then after the ON or USING filtering clauses have been applied, an extra row is added to the output for each row in the original right-hand input dataset that does not match any row in the left-hand dataset. The added rows contain NULL values in the columns that would normally contain values copied from the left-hand input dataset.
-    A "FULL JOIN" or "FULL OUTER JOIN" is a combination of a "LEFT JOIN" and a "RIGHT JOIN". Extra rows of output are added for each row in left dataset that matches no rows in the right, and for each row in the right dataset that matches no rows in the left. Unmatched columns are filled in with NULL.
 When more than two tables are joined together as part of a FROM clause, the join operations are processed in order from left to right. In other words, the FROM clause (A join-op-1 B join-op-2 C) is computed as ((A join-op-1 B) join-op-2 C).
## 2.2. Special handling of CROSS JOIN.
 There is no difference between the "INNER JOIN", "JOIN" and "," join operators. They are completely interchangeable in SQLite. The "CROSS JOIN" join operator produces the same result as the "INNER JOIN", "JOIN" and "," operators, but is handled differently by the query optimizer in that it prevents the query optimizer from reordering the tables in the join. An application programmer can use the CROSS JOIN operator to directly influence the algorithm that is chosen to implement the SELECT statement. Avoid using CROSS JOIN except in specific situations where manual control of the query optimizer is desired. Avoid using CROSS JOIN early in the development of an application as doing so is a premature optimization. The special handling of CROSS JOIN is an SQLite-specific feature and is not a part of standard SQL.
## 2.3. WHERE clause filtering.
 If a WHERE clause is specified, the WHERE expression is evaluated for each row in the input data as a boolean expression. Only rows for which the WHERE clause expression evaluates to true are included from the dataset before continuing. Rows are excluded from the result if the WHERE clause evaluates to either false or NULL.
For a JOIN or INNER JOIN or CROSS JOIN, there is no difference between a constraint expression in the WHERE clause and one in the ON clause. However, for a LEFT or RIGHT or FULL OUTER JOIN, the difference is very important. In an outer join, the extra NULL rows for non-matched rows on the other operand are added after ON clause processing but before WHERE clause processing. A constraint of the form "left.x=right.y" in an ON clause will therefore allow through for the added all-NULL rows. But if that same constraint is in the WHERE clause, a NULL in one of "right.y" or "left.x" will prevent the expression "left.x=right.y" from being true, and thus exclude that row from the output.
## 2.4. Generation of the set of result rows
 Once the input data from the FROM clause has been filtered by the WHERE clause expression (if any), the set of result rows for the simple SELECT are calculated. Exactly how this is done depends on whether the simple SELECT is an aggregate or non-aggregate query, and whether or not a GROUP BY clause was specified.
 The list of expressions between the SELECT and FROM keywords is known as the result expression list. If a result expression is the special expression "*" then all columns in the input data are substituted for that one expression. If the expression is the alias of a table or subquery in the FROM clause followed by ".*" then all columns from the named table or subquery are substituted for the single expression. It is an error to use a "*" or "alias.*" expression in any context other than a result expression list. It is also an error to use a "*" or "alias.*" expression in a simple SELECT query that does not have a FROM clause.
 The number of columns in the rows returned by a simple SELECT statement is equal to the number of expressions in the result expression list after substitution of * and alias.* expressions. Each result row is calculated by evaluating the expressions in the result expression list with respect to a single row of input data or, for aggregate queries, with respect to a group of rows.

- If the SELECT statement is a non-aggregate query, then each expression in the result expression list is evaluated for each row in the dataset filtered by the WHERE clause.
- If the SELECT statement is an aggregate query without a GROUP BY clause, then each aggregate expression in the result-set is evaluated once across the entire dataset. Each non-aggregate expression in the result-set is evaluated once for an arbitrarily selected row of the dataset. The same arbitrarily selected row is used for each non-aggregate expression. Or, if the dataset contains zero rows, then each non-aggregate expression is evaluated against a row consisting entirely of NULL values.
The single row of result-set data created by evaluating the aggregate and non-aggregate expressions in the result-set forms the result of an aggregate query without a GROUP BY clause. An aggregate query without a GROUP BY clause always returns exactly one row of data, even if there are zero rows of input data.
- If the SELECT statement is an aggregate query with a GROUP BY clause, then each of the expressions specified as part of the GROUP BY clause is evaluated for each row of the dataset according to the processing rules stated below for ORDER BY expressions. Each row is then assigned to a "group" based on the results; rows for which the results of evaluating the GROUP BY expressions are the same get assigned to the same group. For the purposes of grouping rows, NULL values are considered equal. The usual rules for selecting a collation sequence with which to compare text values apply when evaluating expressions in a GROUP BY clause. The expressions in the GROUP BY clause do not have to be expressions that appear in the result. The expressions in a GROUP BY clause may not be aggregate expressions.
If a HAVING clause is specified, it is evaluated once for each group of rows as a boolean expression. If the result of evaluating the HAVING clause is false, the group is discarded. If the HAVING clause is an aggregate expression, it is evaluated across all rows in the group. If a HAVING clause is a non-aggregate expression, it is evaluated with respect to an arbitrarily selected row from the group. The HAVING expression may refer to values, even aggregate functions, that are not in the result.
 Each expression in the result-set is then evaluated once for each group of rows. If the expression is an aggregate expression, it is evaluated across all rows in the group. Otherwise, it is evaluated against a single arbitrarily chosen row from within the group. If there is more than one non-aggregate expression in the result-set, then all such expressions are evaluated for the same row.
Each group of input dataset rows contributes a single row to the set of result rows. Subject to filtering associated with the DISTINCT keyword, the number of rows returned by an aggregate query with a GROUP BY clause is the same as the number of groups of rows produced by applying the GROUP BY and HAVING clauses to the filtered input dataset.

## 2.5. Bare columns in an aggregate query
 The usual case is that all column names in an aggregate query are either arguments to aggregate functions or else appear in the GROUP BY clause. A result column which contains a column name that is not within an aggregate function and that does not appear in the GROUP BY clause (if one exists) is called a "bare" column. Example:
```

SELECT a, b, sum(c) FROM tab1 GROUP BY a;
```
 In the query above, the "a" column is part of the GROUP BY clause and so each row of the output contains one of the distinct values for "a". The "c" column is contained within the sum() aggregate function and so that output column is the sum of all "c" values in rows that have the same value for "a". But what is the result of the bare column "b"? The answer is that the "b" result will be the value for "b" in one of the input rows that form the aggregate.¹ The problem is that you usually do not know which input row is used to compute "b", and so in many cases the value for "b" is undefined.
  Special processing occurs when the aggregate function is either min() or max(). Example:
```

SELECT a, b, max(c) FROM tab1 GROUP BY a;
```
 If there is exactly one min() or max() aggregate in the query, then all bare columns in the result set take values from an input row which also contains the minimum or maximum. So in the query above, the value of the "b" column in the output will be the value of the "b" column in the input row that has the largest "c" value. There are limitations on this special behavior of min() and max():

1.  If the same minimum or maximum value occurs on two or more rows, then bare values might be selected from any of those rows. The choice is arbitrary. There is no way to predict from which row the bare values will be choosen. The choice might be different for different bare columns within the same query.
1.  If there are two or more min() or max() aggregates in the query, then bare column values will be taken from one of the rows on which one of the aggregates has their minimum or maximum value. The choice of which min() or max() aggregate determines the selection of bare column values is arbitrary. The choice might be different for different bare columns within the same query.
1.  This special processing for min() or max() aggregates only works for the built-in implementation of those aggregates. If an application overrides the built-in min() or max() aggregates with application-defined alternatives, then the values selected for bare columns will be taken from an arbitrary row.
 Most other SQL database engines disallow bare columns. If you include a bare column in a query, other database engines will usually raise an error. The ability to include bare columns in a query is an SQLite-specific extension. This is considered a feature, not a bug. See the discussion on SQLite Forum thread 7481d2a6df8980ff for additional information.

### 2.5.1. Notes

1.  If the aggregate is composed from one or more input rows, then a bare column will take on the value of an arbitrary row from the aggregate's input. The particular row chosen might change from one invocation to the the next. If the aggregate is empty (if the aggregate has no input rows, as happens if no rows match the WHERE clause), then the bare column can take on any arbitrary value, including values that are not found anywhere in the tables of the FROM clause.

## 2.6. Removal of duplicate rows (DISTINCT processing)
 One of the ALL or DISTINCT keywords may follow the SELECT keyword in a simple SELECT statement. If the simple SELECT is a SELECT ALL, then the entire set of result rows are returned by the SELECT. If neither ALL or DISTINCT are present, then the behavior is as if ALL were specified. If the simple SELECT is a SELECT DISTINCT, then duplicate rows are removed from the set of result rows before it is returned. For the purposes of detecting duplicate rows, values are compared using the IS DISTINCT FROM operator. Thus two NULL values are considered to be equal. An integer is equal to a floating point number if they represent the same quantity. Text values are compared using an appropriate collation sequence. The usual rules apply for selecting a collation sequence to compare text values. BLOB affinity is used for DISTINCT comparisons, hence no type coercions occur.
# 3. Compound Select Statements
 Two or more simple SELECT statements may be connected together to form a compound SELECT using the UNION, UNION ALL, INTERSECT or EXCEPT operator, as shown by the following diagram: compound-select-stmt: hide
         WITH  RECURSIVE      common-table-expression       ,     select-core  ORDER    BY  LIMIT    expr         UNION  UNION    ALL      select-core  INTERSECT  EXCEPT                        ordering-term  ,              OFFSET    expr    ,    expr
 common-table-expression: show
       table-name      (      column-name    )    AS  NOT  MATERIALIZED   (    select-stmt    )     ,
 select-stmt: show
        WITH  RECURSIVE      common-table-expression       ,              SELECT    DISTINCT    result-column  ,        ALL       FROM    table-or-subquery  join-clause  ,                  WHERE    expr           GROUP    BY    expr    HAVING    expr  ,                   WINDOW    window-name    AS    window-defn  ,                    VALUES    (    expr    )     ,  ,          compound-operator      select-core  ORDER    BY  LIMIT    expr    ordering-term  ,                  OFFSET    expr    ,    expr
 compound-operator: show
         UNION  UNION  INTERSECT  EXCEPT    ALL

 join-clause: show
       table-or-subquery    join-operator    table-or-subquery    join-constraint
 join-constraint: show
       USING    (    column-name    )       ,       ON    expr

 join-operator: show
       NATURAL      LEFT    OUTER      JOIN     ,             RIGHT      FULL     INNER       CROSS

 result-column: show
       expr    AS    column-alias               *       table-name    .    *

 table-or-subquery: show
       schema-name    .    table-name    AS    table-alias       INDEXED    BY    index-name  NOT    INDEXED          table-function-name    (    expr    )    ,             AS    table-alias            (    select-stmt    )          (    table-or-subquery    )       ,       join-clause

 window-defn: show
       (    base-window-name  PARTITION    BY    expr  ,              ORDER    BY    ordering-term  ,            frame-spec    )
 frame-spec: show
       GROUPS     BETWEEN    UNBOUNDED    PRECEDING    AND    UNBOUNDED    FOLLOWING     RANGE       ROWS       UNBOUNDED    PRECEDING     expr    PRECEDING       CURRENT    ROW       expr    PRECEDING       CURRENT    ROW       expr    FOLLOWING         expr    PRECEDING     CURRENT    ROW       expr    FOLLOWING       EXCLUDE    CURRENT    ROW     EXCLUDE    GROUP     EXCLUDE    TIES     EXCLUDE    NO    OTHERS

 expr: show
       literal-value     bind-parameter       schema-name    .    table-name    .    column-name             unary-operator    expr       expr    binary-operator    expr       function-name    (    function-arguments    )    filter-clause      over-clause             (    expr    )       ,     CAST    (    expr    AS    type-name    )       expr    COLLATE    collation-name       expr    NOT    LIKE  GLOB  REGEXP  MATCH  expr  expr    ESCAPE    expr                                  expr    ISNULL       NOTNULL  NOT    NULL             expr    IS    NOT      DISTINCT    FROM    expr         expr    NOT    BETWEEN    expr    AND    expr        expr    NOT    IN    (    select-stmt    )         expr     ,     schema-name    .    table-function    (    expr    )     table-name       ,           NOT    EXISTS    (    select-stmt    )           CASE    expr    WHEN    expr    THEN    expr    ELSE    expr    END            raise-function
 filter-clause: show
       FILTER    (    WHERE    expr    )

 function-arguments: show
         DISTINCT        expr         ,      *            ORDER    BY    ordering-term  ,

 literal-value: show
       CURRENT_TIMESTAMP       numeric-literal     string-literal       blob-literal       NULL       TRUE       FALSE       CURRENT_TIME       CURRENT_DATE

 over-clause: show
       OVER    window-name    (    base-window-name  PARTITION    BY    expr  ,              ORDER    BY    ordering-term  ,            frame-spec    )
 frame-spec: show
       GROUPS     BETWEEN    UNBOUNDED    PRECEDING    AND    UNBOUNDED    FOLLOWING     RANGE       ROWS       UNBOUNDED    PRECEDING     expr    PRECEDING       CURRENT    ROW       expr    PRECEDING       CURRENT    ROW       expr    FOLLOWING         expr    PRECEDING     CURRENT    ROW       expr    FOLLOWING       EXCLUDE    CURRENT    ROW     EXCLUDE    GROUP     EXCLUDE    TIES     EXCLUDE    NO    OTHERS

 raise-function: show
       RAISE    (    ROLLBACK    ,    expr    )       IGNORE     ABORT     FAIL

 select-stmt: show
        WITH  RECURSIVE      common-table-expression       ,              SELECT    DISTINCT    result-column  ,        ALL       FROM    table-or-subquery  join-clause  ,                  WHERE    expr           GROUP    BY    expr    HAVING    expr  ,                   WINDOW    window-name    AS    window-defn  ,                    VALUES    (    expr    )     ,  ,          compound-operator      select-core  ORDER    BY  LIMIT    expr    ordering-term  ,                  OFFSET    expr    ,    expr
 compound-operator: show
         UNION  UNION  INTERSECT  EXCEPT    ALL

 join-clause: show
       table-or-subquery    join-operator    table-or-subquery    join-constraint
 join-constraint: show
       USING    (    column-name    )       ,       ON    expr

 join-operator: show
       NATURAL      LEFT    OUTER      JOIN     ,             RIGHT      FULL     INNER       CROSS

 result-column: show
       expr    AS    column-alias               *       table-name    .    *

 table-or-subquery: show
       schema-name    .    table-name    AS    table-alias       INDEXED    BY    index-name  NOT    INDEXED          table-function-name    (    expr    )    ,             AS    table-alias            (    select-stmt    )          (    table-or-subquery    )       ,       join-clause

 window-defn: show
       (    base-window-name  PARTITION    BY    expr  ,              ORDER    BY    ordering-term  ,            frame-spec    )
 frame-spec: show
       GROUPS     BETWEEN    UNBOUNDED    PRECEDING    AND    UNBOUNDED    FOLLOWING     RANGE       ROWS       UNBOUNDED    PRECEDING     expr    PRECEDING       CURRENT    ROW       expr    PRECEDING       CURRENT    ROW       expr    FOLLOWING         expr    PRECEDING     CURRENT    ROW       expr    FOLLOWING       EXCLUDE    CURRENT    ROW     EXCLUDE    GROUP     EXCLUDE    TIES     EXCLUDE    NO    OTHERS

 type-name: show
       name    (    signed-number    ,    signed-number    )       (    signed-number    )
 signed-number: show
       +    numeric-literal       -

 ordering-term: show
       expr    COLLATE    collation-name         DESC    ASC          NULLS    FIRST    NULLS    LAST

 select-core: show
       SELECT    DISTINCT    result-column  ,        ALL       FROM    table-or-subquery  join-clause  ,                  WHERE    expr           GROUP    BY    expr    HAVING    expr  ,                   WINDOW    window-name    AS    window-defn  ,                     VALUES    (    expr    )       ,  ,
 join-clause: show
       table-or-subquery    join-operator    table-or-subquery    join-constraint
 join-constraint: show
       USING    (    column-name    )       ,       ON    expr

 join-operator: show
       NATURAL      LEFT    OUTER      JOIN     ,             RIGHT      FULL     INNER       CROSS

 result-column: show
       expr    AS    column-alias               *       table-name    .    *

 table-or-subquery: show
       schema-name    .    table-name    AS    table-alias       INDEXED    BY    index-name  NOT    INDEXED          table-function-name    (    expr    )    ,             AS    table-alias            (    select-stmt    )          (    table-or-subquery    )       ,       join-clause
 select-stmt: show
        WITH  RECURSIVE      common-table-expression       ,              SELECT    DISTINCT    result-column  ,        ALL       FROM    table-or-subquery  join-clause  ,                  WHERE    expr           GROUP    BY    expr    HAVING    expr  ,                   WINDOW    window-name    AS    window-defn  ,                    VALUES    (    expr    )     ,  ,          compound-operator      select-core  ORDER    BY  LIMIT    expr    ordering-term  ,                  OFFSET    expr    ,    expr
 compound-operator: show
         UNION  UNION  INTERSECT  EXCEPT    ALL

 window-defn: show
       (    base-window-name  PARTITION    BY    expr  ,              ORDER    BY    ordering-term  ,            frame-spec    )
 frame-spec: show
       GROUPS     BETWEEN    UNBOUNDED    PRECEDING    AND    UNBOUNDED    FOLLOWING     RANGE       ROWS       UNBOUNDED    PRECEDING     expr    PRECEDING       CURRENT    ROW       expr    PRECEDING       CURRENT    ROW       expr    FOLLOWING         expr    PRECEDING     CURRENT    ROW       expr    FOLLOWING       EXCLUDE    CURRENT    ROW     EXCLUDE    GROUP     EXCLUDE    TIES     EXCLUDE    NO    OTHERS

In a compound SELECT, all the constituent SELECTs must return the same number of result columns. As the components of a compound SELECT must be simple SELECT statements, they may not contain ORDER BY or LIMIT clauses. ORDER BY and LIMIT clauses may only occur at the end of the entire compound SELECT, and then only if the final element of the compound is not a VALUES clause.
A compound SELECT created using the UNION ALL operator returns all the rows from the SELECT to the left of the UNION ALL operator, and all the rows from the SELECT to the right of it. The UNION operator works the same way as UNION ALL, except that duplicate rows are removed from the final result set. The INTERSECT operator returns the intersection of the results of the left and right SELECTs. The EXCEPT operator returns the subset of rows returned by the left SELECT that are not also returned by the right-hand SELECT. Duplicate rows are removed from the results of INTERSECT and EXCEPT operators before the result set is returned.
For the purposes of determining duplicate rows for the results of compound SELECT operators, NULL values are considered equal to other NULL values and distinct from all non-NULL values. The collation sequence used to compare two text values is determined as if the columns of the left and right-hand SELECT statements were the left and right-hand operands of the equals (=) operator, except that greater precedence is not assigned to a collation sequence specified with the postfix COLLATE operator. No affinity transformations are applied to any values when comparing rows as part of a compound SELECT.
When three or more simple SELECTs are connected into a compound SELECT, they group from left to right. In other words, if "A", "B" and "C" are all simple SELECT statements, (A op B op C) is processed as ((A op B) op C).

# 4. The ORDER BY clause
 If a SELECT statement that returns more than one row does not have an ORDER BY clause, the order in which the rows are returned is undefined. Or, if a SELECT statement does have an ORDER BY clause, then the list of expressions attached to the ORDER BY determine the order in which rows are returned to the user.
 In a compound SELECT statement, only the last or right-most simple SELECT may have an ORDER BY clause. That ORDER BY clause will apply across all elements of the compound. If the right-most element of a compound SELECT is a VALUES clause, then no ORDER BY clause is allowed on that statement.
Rows are first sorted based on the results of evaluating the left-most expression in the ORDER BY list, then ties are broken by evaluating the second left-most expression and so on. The order in which two rows for which all ORDER BY expressions evaluate to equal values are returned is undefined. Each ORDER BY expression may be optionally followed by one of the keywords ASC (smaller values are returned first) or DESC (larger values are returned first). If neither ASC or DESC are specified, rows are sorted in ascending (smaller values first) order by default.
SQLite considers NULL values to be smaller than any other values for sorting purposes. Hence, NULLs naturally appear at the beginning of an ASC order-by and at the end of a DESC order-by. This can be changed using the "ASC NULLS LAST" or "DESC NULLS FIRST" syntax.
Each ORDER BY expression is processed as follows:

1. If the ORDER BY expression is a constant integer K then the expression is considered an alias for the K-th column of the result set (columns are numbered from left to right starting with 1).
1. If the ORDER BY expression is an identifier that corresponds to the alias of one of the output columns, then the expression is considered an alias for that column.
1. Otherwise, if the ORDER BY expression is any other expression, it is evaluated and the returned value used to order the output rows. If the SELECT statement is a simple SELECT, then an ORDER BY may contain any arbitrary expressions. However, if the SELECT is a compound SELECT, then ORDER BY expressions that are not aliases to output columns must be exactly the same as an expression used as an output column.
 For the purposes of sorting rows, values are compared in the same way as for comparison expressions. The collation sequence used to compare two text values is determined as follows:

1. If the ORDER BY expression is assigned a collation sequence using the postfix COLLATE operator, then the specified collation sequence is used.
1. Otherwise, if the ORDER BY expression is an alias to an expression that has been assigned a collation sequence using the postfix COLLATE operator, then the collation sequence assigned to the aliased expression is used.
1. Otherwise, if the ORDER BY expression is a column or an alias of an expression that is a column, then the default collation sequence for the column is used.
1. Otherwise, the BINARY collation sequence is used.
 In a compound SELECT statement, all ORDER BY expressions are handled as aliases for one of the result columns of the compound. If an ORDER BY expression is not an integer alias, then SQLite searches the left-most SELECT in the compound for a result column that matches either the second or third rules above. If a match is found, the search stops and the expression is handled as an alias for the result column that it has been matched against. Otherwise, the next SELECT to the right is tried, and so on. If no matching expression can be found in the result columns of any constituent SELECT, it is an error. Each term of the ORDER BY clause is processed separately and may be matched against result columns from different SELECT statements in the compound.

# 5. The LIMIT clause
 The LIMIT clause is used to place an upper bound on the number of rows returned by the entire SELECT statement.
In a compound SELECT, only the last or right-most simple SELECT may contain a LIMIT clause. In a compound SELECT, the LIMIT clause applies to the entire compound, not just the final SELECT. If the right-most simple SELECT is a VALUES clause then no LIMIT clause is allowed.
Any scalar expression may be used in the LIMIT clause, so long as it evaluates to an integer or a value that can be losslessly converted to an integer. If the expression evaluates to a NULL value or any other value that cannot be losslessly converted to an integer, an error is returned. If the LIMIT expression evaluates to a negative value, then there is no upper bound on the number of rows returned. Otherwise, the SELECT returns the first N rows of its result set only, where N is the value that the LIMIT expression evaluates to. Or, if the SELECT statement would return less than N rows without a LIMIT clause, then the entire result set is returned.
The expression attached to the optional OFFSET clause that may follow a LIMIT clause must also evaluate to an integer, or a value that can be losslessly converted to an integer. If an expression has an OFFSET clause, then the first M rows are omitted from the result set returned by the SELECT statement and the next N rows are returned, where M and N are the values that the OFFSET and LIMIT clauses evaluate to, respectively. Or, if the SELECT would return less than M+N rows if it did not have a LIMIT clause, then the first M rows are skipped and the remaining rows (if any) are returned. If the OFFSET clause evaluates to a negative value, the results are the same as if it had evaluated to zero.
Instead of a separate OFFSET clause, the LIMIT clause may specify two scalar expressions separated by a comma. In this case, the first expression is used as the OFFSET expression and the second as the LIMIT expression. This is counter-intuitive, as when using the OFFSET clause the second of the two expressions is the OFFSET and the first the LIMIT. This reversal of the offset and limit is intentional - it maximizes compatibility with other SQL database systems. However, to avoid confusion, programmers are strongly encouraged to use the form of the LIMIT clause that uses the "OFFSET" keyword and avoid using a LIMIT clause with a comma-separated offset.
# 6. The VALUES clause
 The phrase "VALUES(expr-list)" means the same thing as "SELECT expr-list". The phrase "VALUES(expr-list-1),...,(expr-list-N)" means the same thing as "SELECT expr-list-1 UNION ALL ... UNION ALL SELECT expr-list-N". Both forms are the same, except that the number of SELECT statements in a compound is limited by SQLITE_LIMIT_COMPOUND_SELECT whereas the number of rows in a VALUES clause has no arbitrary limit.
There are some restrictions on the use of a VALUES clause that are not shown on the syntax diagrams:

-  A VALUES clause cannot be followed by ORDER BY.
-  A VALUES clause cannot be followed by LIMIT.

# 7. The WITH Clause
 SELECT statements may be optionally preceded by a single WITH clause that defines one or more common table expressions for use within the SELECT statement.
# 8. Table-valued Functions In The FROM Clause
 A virtual table that contains hidden columns can be used like a table-valued function in the FROM clause. The arguments to the table-valued function become constraints on the HIDDEN columns of the virtual table. Additional information can be found in the virtual table documentation.
# 9. Deviations From Standard SQL
 The SELECT syntax of SQLite differs slightly from standard SQL. These differences are due to several reasons:

-  In the mid-2000s, there was a lot of emphasis on keeping the library footprint as small as possible, so as not to use too much space on memory-limited flip-phones and similar.
-  During the early years of SQLite, the lead developer sought to follow Postel's Law and to be forgiving and flexible in what input was accepted.
-  There were bugs in early SQLite parsers that accepts some strange inputs.
-  The lead developer's knowledge of SQL was imperfect.
 Whatever the origin of the input quirks, we generally avoid trying to "fix" them, as any new restrictions on the input syntax would likely cause at least some of the millions of applications that use SQLite to break. We do not want that. The goal of the SQLite development team is to preserve backwards compability to the fullest extent possible. Hence, if a syntax quirk is harmless, we leave it alone and document it here, rather than try to fix it.
## 9.1. Strange JOIN names
 SQLite accepts all of the usual syntax for JOIN operators: join-operator: hide
       NATURAL      LEFT    OUTER      JOIN     ,             RIGHT      FULL     INNER       CROSS

But it does not stop there. SQLite is actually very flexible in how you specify a join operator. The general syntax is:
 blah blah blah JOIN  Where there are between 1 and 3 instances of "blah", each of which can be any of "CROSS", "FULL", "INNER", "LEFT", "NATURAL", "OUTER", or "RIGHT". The SQLite parser treats each of these keywords as an attribute of the join, which can be combined in any order. This creates the possibility of many new and creative join types beyond what is specified by the syntax diagram. Some of these non-standard join types are specifically disallowed. For example, you cannot say "INNER OUTER JOIN", because that would be contradictory. But you can say things like "OUTER LEFT NATURAL JOIN" which means the same as "NATURAL LEFT OUTER JOIN". Or you can say "LEFT RIGHT JOIN" which is the same as "FULL JOIN".
Remember: you can use these non-standard join types but you ought not. Stick to using standard JOIN syntax for portability with other SQL database engines.
## 9.2. Flexible join syntax
 Standard SQL has tighter restrictions on join syntax than does SQLite. In standard SQL, all joins other than comma-joins, CROSS JOINs, and NATURAL joins must have either an ON clause or a USING clause and comma-joins, CROSS JOINs, and NATURAL joins must not have either an ON or USING clause. SQLite is not nearly so fussy about join syntax. SQLite will accept and process an ON or USING clause on a comma-join or CROSS JOIN, and will let you omit the ON or USING clause from any join at all. In SQLite, the only restrictions are:

-  You cannot have an ON or USING clause on a NATURAL join.
-  You cannot have both an ON clause and a USING clause on the same join.
  SQLite even allows you to omit the ON or USING clause from an outer join, though doing so means that the outer join is unconstrained (as if the ON clause where "
```
ON true
```
") which make the outer join behave like an inner join.
## 9.3. Precedence of comma-joins and CROSS JOIN
 In standard SQL, joins that use the JOIN keyword take higher precedence than comma-joins. That is to say, JOIN operators happen before comma operators. This is not the case in SQLite, where all joins have the same precedence.
Consider this example:
```

... FROM t1, t2 NATURAL FULL JOIN t3 ...
```
 In standard SQL, the FULL JOIN between t2 and t3 would occur first, and then the result of the left join would be cross-joined against t1. But SQLite always handles all joins from left to right. Thus, SQLite will do a cross join on t1 and t2 first, then the result of that cross join will feed into the FULL JOIN with t3. Inner joins are inherently associative, so the difference is only evident if your FROM clause contains one or more outer joins.
You can work around this, and make your SQL statements portable across all systems, by observing the following stylistic rules:

-  Do not mix comma-joins with the JOIN keyword. It is fine to use comma-joins, but if you do, the you should use only comma-joins for the entire FROM clause.
-  Prefer LEFT JOIN over other outer join operators.
-  When in doubt, use parentheses to specify the exact join order that you intend.
 Any one of these suggestions is sufficient to avoid problems, and most programmers instinctively follow all of these suggestions without having to be told, and so the lack of precedence difference between comma-joins and the JOIN keyword in SQLite rarely comes up in practice. But you should be aware of the problem, in case it ever does appear.
This page was last updated on 2026-01-26 15:45:07Z

# INSERT

Small. Fast. Reliable.Choose any three.

- Home
- Menu
- About
- Documentation
- Download
- License
- Support
- Purchase
-  Search

- About
- Documentation
- Download
- Support
- Purchase

    Search Documentation Search Changelog

     INSERT

# 1. Overview
 insert-stmt: hide
       WITH  RECURSIVE      common-table-expression       ,         REPLACE  INSERT    OR    ROLLBACK      INTO           ABORT       FAIL       IGNORE       REPLACE       schema-name    .    table-name    AS    alias           (    column-name    )  ,               VALUES    (    expr    )    ,     ,       upsert-clause       select-stmt       upsert-clause       DEFAULT    VALUES      returning-clause
 common-table-expression: show
       table-name      (      column-name    )    AS  NOT  MATERIALIZED   (    select-stmt    )     ,

 expr: show
       literal-value     bind-parameter       schema-name    .    table-name    .    column-name             unary-operator    expr       expr    binary-operator    expr       function-name    (    function-arguments    )    filter-clause      over-clause             (    expr    )       ,     CAST    (    expr    AS    type-name    )       expr    COLLATE    collation-name       expr    NOT    LIKE  GLOB  REGEXP  MATCH  expr  expr    ESCAPE    expr                                  expr    ISNULL       NOTNULL  NOT    NULL             expr    IS    NOT      DISTINCT    FROM    expr         expr    NOT    BETWEEN    expr    AND    expr        expr    NOT    IN    (    select-stmt    )         expr     ,     schema-name    .    table-function    (    expr    )     table-name       ,           NOT    EXISTS    (    select-stmt    )           CASE    expr    WHEN    expr    THEN    expr    ELSE    expr    END            raise-function
 filter-clause: show
       FILTER    (    WHERE    expr    )

 function-arguments: show
         DISTINCT        expr         ,      *            ORDER    BY    ordering-term  ,
 ordering-term: show
       expr    COLLATE    collation-name         DESC    ASC          NULLS    FIRST    NULLS    LAST

 literal-value: show
       CURRENT_TIMESTAMP       numeric-literal     string-literal       blob-literal       NULL       TRUE       FALSE       CURRENT_TIME       CURRENT_DATE

 over-clause: show
       OVER    window-name    (    base-window-name  PARTITION    BY    expr  ,              ORDER    BY    ordering-term  ,            frame-spec    )
 frame-spec: show
       GROUPS     BETWEEN    UNBOUNDED    PRECEDING    AND    UNBOUNDED    FOLLOWING     RANGE       ROWS       UNBOUNDED    PRECEDING     expr    PRECEDING       CURRENT    ROW       expr    PRECEDING       CURRENT    ROW       expr    FOLLOWING         expr    PRECEDING     CURRENT    ROW       expr    FOLLOWING       EXCLUDE    CURRENT    ROW     EXCLUDE    GROUP     EXCLUDE    TIES     EXCLUDE    NO    OTHERS

 ordering-term: show
       expr    COLLATE    collation-name         DESC    ASC          NULLS    FIRST    NULLS    LAST

 raise-function: show
       RAISE    (    ROLLBACK    ,    expr    )       IGNORE     ABORT     FAIL

 type-name: show
       name    (    signed-number    ,    signed-number    )       (    signed-number    )
 signed-number: show
       +    numeric-literal       -

 returning-clause: show
       RETURNING    expr    AS    column-alias               *       ,

 select-stmt: show
        WITH  RECURSIVE      common-table-expression       ,              SELECT    DISTINCT    result-column  ,        ALL       FROM    table-or-subquery  join-clause  ,                  WHERE    expr           GROUP    BY    expr    HAVING    expr  ,                   WINDOW    window-name    AS    window-defn  ,                    VALUES    (    expr    )     ,  ,          compound-operator      select-core  ORDER    BY  LIMIT    expr    ordering-term  ,                  OFFSET    expr    ,    expr
 compound-operator: show
         UNION  UNION  INTERSECT  EXCEPT    ALL

 join-clause: show
       table-or-subquery    join-operator    table-or-subquery    join-constraint
 join-constraint: show
       USING    (    column-name    )       ,       ON    expr

 join-operator: show
       NATURAL      LEFT    OUTER      JOIN     ,             RIGHT      FULL     INNER       CROSS

 ordering-term: show
       expr    COLLATE    collation-name         DESC    ASC          NULLS    FIRST    NULLS    LAST

 result-column: show
       expr    AS    column-alias               *       table-name    .    *

 table-or-subquery: show
       schema-name    .    table-name    AS    table-alias       INDEXED    BY    index-name  NOT    INDEXED          table-function-name    (    expr    )    ,             AS    table-alias            (    select-stmt    )          (    table-or-subquery    )       ,       join-clause

 window-defn: show
       (    base-window-name  PARTITION    BY    expr  ,              ORDER    BY    ordering-term  ,            frame-spec    )
 frame-spec: show
       GROUPS     BETWEEN    UNBOUNDED    PRECEDING    AND    UNBOUNDED    FOLLOWING     RANGE       ROWS       UNBOUNDED    PRECEDING     expr    PRECEDING       CURRENT    ROW       expr    PRECEDING       CURRENT    ROW       expr    FOLLOWING         expr    PRECEDING     CURRENT    ROW       expr    FOLLOWING       EXCLUDE    CURRENT    ROW     EXCLUDE    GROUP     EXCLUDE    TIES     EXCLUDE    NO    OTHERS

 upsert-clause: show
        ON    CONFLICT    (    indexed-column    )    WHERE    expr      DO      ,    conflict target      UPDATE    SET    column-name-list    =    expr    WHERE    expr     NOTHING       ,         column-name
 column-name-list: show
       (      column-name    )     ,

 indexed-column: show
       column-name    COLLATE    collation-name      DESC         expr          ASC

 The INSERT statement comes in three basic forms.

1. INSERT INTO table VALUES(...);
The first form (with the "VALUES" keyword) creates one or more new rows in an existing table. If the column-name list after table-name is omitted then the number of values inserted into each row must be the same as the number of columns in the table. In this case the result of evaluating the left-most expression from each term of the VALUES list is inserted into the left-most column of each new row, and so forth for each subsequent expression. If a column-name list is specified, then the number of values in each term of the VALUE list must match the number of specified columns. Each of the named columns of the new row is populated with the results of evaluating the corresponding VALUES expression. Table columns that do not appear in the column list are populated with the default column value (specified as part of the CREATE TABLE statement), or with NULL if no default value is specified.
1. INSERT INTO table SELECT ...;
The second form of the INSERT statement contains a SELECT statement instead of a VALUES clause. A new entry is inserted into the table for each row of data returned by executing the SELECT statement. If a column-list is specified, the number of columns in the result of the SELECT must be the same as the number of items in the column-list. Otherwise, if no column-list is specified, the number of columns in the result of the SELECT must be the same as the number of columns in the table. Any SELECT statement, including compound SELECTs and SELECT statements with ORDER BY and/or LIMIT clauses, may be used in an INSERT statement of this form.
To avoid a parsing ambiguity, the SELECT statement should always contain a WHERE clause, even if that clause is simply "WHERE true", if the upsert-clause is present. Without the WHERE clause, the parser does not know if the token "ON" is part of a join constraint on the SELECT, or the beginning of the upsert-clause.
1. INSERT INTO table DEFAULT VALUES;
The third form of an INSERT statement is with DEFAULT VALUES. The INSERT ... DEFAULT VALUES statement inserts a single new row into the named table. Each column of the new row is populated with its default value, or with a NULL if no default value is specified as part of the column definition in the CREATE TABLE statement. The upsert-clause is not supported after DEFAULT VALUES.
  The initial "INSERT" keyword can be replaced by "REPLACE" or "INSERT OR action" to specify an alternative constraint conflict resolution algorithm to use during that one INSERT command. For compatibility with MySQL, the parser allows the use of the single keyword REPLACE as an alias for "INSERT OR REPLACE".
The optional "schema-name." prefix on the table-name is supported for top-level INSERT statements only. The table name must be unqualified for INSERT statements that occur within CREATE TRIGGER statements. Similarly, the "DEFAULT VALUES" form of the INSERT statement is supported for top-level INSERT statements only and not for INSERT statements within triggers.

The optional "AS alias" phrase provides an alternative name for the table into which content is being inserted. The alias name can be used within WHERE and SET clauses of the UPSERT. If there is no upsert-clause, then the alias is pointless, but also harmless.
See the separate UPSERT documentation for the additional trailing syntax that can cause an INSERT to behave as an UPDATE if the INSERT would otherwise violate a uniqueness constraint. The upsert clause is not allowed on an "INSERT ... DEFAULT VALUES".
This page was last updated on 2026-05-14 15:13:28Z
