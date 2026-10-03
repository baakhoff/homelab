-- Money moved per day, by currency, direction, category and budget.
select
  booked_on as day,
  currency_code,
  type,
  if(category_name = '', '(none)', category_name) as category,
  if(budget_name = '', '(none)', budget_name) as budget,
  sum(coalesce(amount, 0)) as amount,
  count() as splits
from {{ ref('firefly_transactions') }}
where booked_on is not null
group by day, currency_code, type, category, budget
