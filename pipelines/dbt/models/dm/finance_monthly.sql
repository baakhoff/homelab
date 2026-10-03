-- Income, spending and net per month, currency and category: the table a
-- budget review reads. Transfers between own accounts are left out.
select
  toStartOfMonth(day) as month,
  currency_code,
  category,
  sumIf(amount, type = 'deposit') as income,
  sumIf(amount, type = 'withdrawal') as spending,
  income - spending as net,
  sum(splits) as transactions
from {{ ref('finance_daily') }}
where type in ('deposit', 'withdrawal')
group by month, currency_code, category
