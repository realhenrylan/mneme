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
