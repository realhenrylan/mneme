### 导航

-  索引

-  模块 |

-  下一页 |

-  上一页 |

-

- Python »

-

-

-  3.14.6 Documentation »

- Python 标准库 »

- 数据类型 »

-
```
datetime
```
 --- 基本日期和时间类型

-
 |

-   主题  自动 明亮 黑暗   |

#
```
datetime
```
 --- 基本日期和时间类型¶
 源代码： Lib/datetime.py

```
datetime
```
 模块提供了用于操作日期和时间的类。
 在支持日期时间数学运算的同时，实现的关注点更着重于如何能够更有效地解析其属性用于格式化输出和数据操作。
  小技巧
 跳到 格式代码。

  参见
  模块
```
calendar
```
通用日历相关函数

 模块
```
time
```
时间的访问和转换

```
zoneinfo
```
 模块
代表 IANA 时区数据库的具体时区。

 dateutil 包
具有扩展时区和解析支持的第三方库。

 包 DateType
引入了独特静态类型的第三方库，例如允许 静态类型检查器 区分简单型和感知型日期时间。

## 感知型对象和简单型对象¶
 日期和时间对象可以根据它们是否包含时区信息而分为“感知型”和“简单型”两类。
 充分掌握应用性算法和政治性时间调整信息例如时区和夏令时的情况下，一个 感知型 对象就能相对于其他感知型对象来精确定位自身时间点。 感知型对象是用来表示一个没有解释空间的固定时间点。 [1]
 简单型 对象没有包含足够多的信息来无歧义地相对于其他 date/time 对象来定位自身时间点。 不论一个简单型对象所代表的是世界标准时间（UTC）、当地时间还是某个其他时区的时间完全取决于具体程序，就像一个特定数字所代表的是米、英里还是质量完全取决于具体程序一样。 简单型对象更易于理解和使用，代价则是忽略了某些现实性考量。
 对于要求感知型对象的应用程序，
```
datetime
```
 和
```
time
```
 对象具有一个可选的时区信息属性
```
tzinfo
```
，它可被设为抽象类
```
tzinfo
```
 的子类的一个实例。 这些
```
tzinfo
```
 对象会捕获与 UTC 时间的差值、时区名称以及夏令时是否生效等信息。

```
datetime
```
 模块只提供了一个具体的
```
tzinfo
```
 类，即
```
timezone
```
 类。
```
timezone
```
 类可以表示具有相对于 UTC 的固定时差的简单时区，例如 UTC 本身或北美 EST 和 EDT 时区等。 支持时区的详细程度取决于具体的应用。 世界各地的时间调整规则往往是政治性多于合理性，经常会发生变化，除了 UTC 之外并没有一个能适合所有应用的标准。

## 常量¶

```
datetime
```
 模块导出了以下常量：
   datetime.MINYEAR¶

```
date
```
 或
```
datetime
```
 对象允许的最小年份数值。
```
MINYEAR
```
 为 1。

   datetime.MAXYEAR¶

```
date
```
 或
```
datetime
```
 对象允许的最大年份数值。
```
MAXYEAR
```
 为 9999。

   datetime.UTC¶
 UTC 时区单例
```
datetime.timezone.utc
```
 的别名。
  Added in version 3.11.

## 可用的类型¶
   class datetime.date
 一个理想化的简单型日期，它假设当今的公历在过去和未来永远有效。 属性:
```
year
```
,
```
month
```
, and
```
day
```
。

   class datetime.time
 一个独立于任何特定日期的理想化时间，它假设每一天都恰好等于 24*60*60 秒。 （这里没有“闰秒”的概念。） 包含属性:
```
hour
```
,
```
minute
```
,
```
second
```
,
```
microsecond
```
 和
```
tzinfo
```
。

   class datetime.datetime
 日期和时间的结合。属性：
```
year
```
,
```
month
```
,
```
day
```
,
```
hour
```
,
```
minute
```
,
```
second
```
,
```
microsecond
```
, and
```
tzinfo
```
.

   class datetime.timedelta
 将两个
```
datetime
```
 或
```
date
```
 实例之间的差值表示为微秒级精度的持续时间。

   class datetime.tzinfo
 一个描述时区信息对象的抽象基类。 用来给
```
datetime
```
 和
```
time
```
 类提供自定义的时间调整概念（例如处理时区和/或夏令时）。

   class datetime.timezone
 一个实现了
```
tzinfo
```
 抽象基类的子类，用于表示相对于 世界标准时间（UTC）的偏移量。
  Added in version 3.2.

 这些类型的对象都是不可变的。
 子类关系：

### 通用特征属性¶

```
date
```
,
```
datetime
```
,
```
time
```
 和
```
timezone
```
 类型共享这些通用特性:

- 这些类型的对象都是不可变的。

- 这些类型的对象是 hashable，意味着它们可以被用作字典的键。

- 这些类型的对象支持通过
```
pickle
```
 模块进行高效的封存。

### 确定一个对象是感知型还是简单型¶

```
date
```
 类型的对象都是简单型的。

```
time
```
 或
```
datetime
```
 类型的对象可以是感知型或者简单型。
 一个
```
datetime
```
 对象
```
d
```
 在以下条件同时成立时将是感知型的：

1.
```
d.tzinfo
```
 不为
```
None
```

1.
```
d.tzinfo.utcoffset(d)
```
 不返回
```
None
```

 在其他情况下，
```
d
```
 将是简单型的。
 一个
```
time
```
 对象
```
t
```
 在以下条件同时成立时将是感知型的：

1.
```
t.tzinfo
```
 不为
```
None
```

1.
```
t.tzinfo.utcoffset(None)
```
 不返回
```
None
```
。

 在其他情况下，
```
t
```
 将是简单型的。
 感知型和简单型之间的区别不适用于
```
timedelta
```
 对象。

##
```
timedelta
```
 对象¶

```
timedelta
```
 对象表示一段持续的时间，即两个
```
datetime
```
 或
```
date
```
 实例之间的差值。
   class datetime.timedelta(days=0, seconds=0, microseconds=0, milliseconds=0, minutes=0, hours=0, weeks=0)¶
 所有参数都是可选的并且默认为 0。 这些参数可以是整数或者浮点数，并可以为正值或者负值。
 只有 days, seconds 和 microseconds 会存储在内部。 参数单位的换算规则如下：

- 1毫秒会转换成1000微秒。

- 1分钟会转换成60秒。

- 1小时会转换成3600秒。

- 1星期会转换成7天。

 日期、秒、微秒都是标准化的，所以它们的表达方式也是唯一的，例：

-
```
0 <= microseconds < 1000000
```

-
```
0 <= seconds < 3600*24
```
 (一天的秒数)

-
```
-999999999 <= days <= 999999999
```

 下面的例子演示了如何对 days, seconds 和 microseconds 以外的任意参数执行“合并”操作并标准化为以上三个结果属性:

```
>>> import datetime as dt
>>> delta = dt.timedelta(
...     days=50,
...     seconds=27,
...     microseconds=10,
...     milliseconds=29000,
...     minutes=5,
...     hours=8,
...     weeks=2
... )
>>> # Only days, seconds, and microseconds remain
>>> delta
datetime.timedelta(days=64, seconds=29156, microseconds=10)
```

  小技巧
 使用
```
import datetime as dt
```
 而不是
```
import datetime
```
 或
```
from datetime import datetime
```
 以避免模块和类之间的混淆。 参见 How I Import Python’s datetime Module。

 在有任何参数为浮点型并且 microseconds 值为小数的情况下，从所有参数中余下的微秒数将被合并，并使用四舍五入偶不入奇的规则将总计值舍入到最接近的整数微秒值。 如果没有任何参数为浮点型的情况下，则转换和标准化过程将是完全精确的（不会丢失信息）。
 如果标准化后的 days 数值超过了指定范围，将会抛出
```
OverflowError
```
 异常。
 请注意对负数值进行标准化的结果可能会令人感到惊讶。 例如:

```
>>> import datetime as dt
>>> d = dt.timedelta(microseconds=-1)
>>> (d.days, d.seconds, d.microseconds)
(-1, 86399, 999999)
```

 由于
```
timedelta
```
 对象的字符串表示形式可能难以理解，请使用下面的方式来产生更具可读性的格式：

```
>>> def pretty_timedelta(td):
...     if td.days >= 0:
...         return str(td)
...     return f'-({-td!s})'
...
>>> d = timedelta(hours=-1)
>>> str(d)  # 对人类不够友好
'-1 day, 23:00:00'
>>> pretty_timedelta(d)
'-(1:00:00)'
```

 类属性：
   timedelta.min¶
 The most negative
```
timedelta
```
 object,
```
timedelta(-999999999)
```
.

   timedelta.max¶
 The most positive
```
timedelta
```
 object,
```
timedelta(days=999999999,
hours=23, minutes=59, seconds=59, microseconds=999999)
```
.

   timedelta.resolution¶
 两个不相等的
```
timedelta
```
 类对象最小的间隔为
```
timedelta(microseconds=1)
```
。

 请注意，因为标准化的缘故，
```
timedelta.max
```
 大于
```
-timedelta.min
```
。
```
-timedelta.max
```
 不可以表示为一个
```
timedelta
```
 对象。
 实例属性（只读）：
   timedelta.days¶
 -999,999,999 至 999,999,999 闭区间。

   timedelta.seconds¶
 0 至 86,399 闭区间。
  小心
 一个有点常见的代码错误是当实际是要获取
```
total_seconds()
```
 值时无意中使用了这个属性：

```
>>> import datetime as dt
>>> duration = dt.timedelta(seconds=11235813)
>>> duration.days, duration.seconds
(130, 3813)
>>> duration.total_seconds()
11235813.0
```

   timedelta.microseconds¶
 0 至 999,999 闭区间。

 支持的运算：

运算
 结果：

 |
```
t1 = t2 + t3
```
  |
```
t2
```
 和
```
t3
```
 之和。 运算后
```
t1 - t2 == t3
```
 且
```
t1 - t3 == t2
```
 为真值。 (1)

 |
```
t1 = t2 - t3
```
  |
```
t2
```
 和
```
t3
```
 之差。 运算后
```
t1 == t2 - t3
```
 且
```
t2 == t1 + t3
```
 为真值。 (1)(6)

 |
```
t1 = t2 * i or t1 = i * t2
```
  | 时差乘以一个整数。 运算后如果
```
i != 0
```
 则
```
t1 // i == t2
```
 为真值。

 |   | 通常情况下，
```
t1  * i == t1 * (i-1) + t1
```
 为真值。 (1)

 |
```
t1 = t2 * f or t1 = f * t2
```
  | 乘以一个浮点数，结果会被舍入到 timedelta 最接近的整数倍。 精度使用四舍五偶入奇不入规则。

 |
```
f = t2 / t3
```
  | 总时长
```
t2
```
 除以间隔单位
```
t3
```
 (3)。 返回一个
```
float
```
 对象。

 |
```
t1 = t2 / f or t1 = t2 / i
```
  | 除以一个浮点数或整数。 结果会被舍入到 timedelta 最接近的整数倍。 精度使用四舍五偶入奇不入规则。

 |
```
t1 = t2 // i
```
 or
```
t1 = t2 // t3
```
  | 计算底数，其余部分（如果有）将被丢弃。在第二种情况下，将返回整数。 （3）

 |
```
t1 = t2 % t3
```
  | 余数为一个
```
timedelta
```
 对象。(3)

 |
```
q, r = divmod(t1, t2)
```
  | 计算商和余数:
```
q = t1 // t2
```
 (3) 和
```
r = t1 % t2
```
。
```
q
```
 是一个整数而
```
r
```
 是一个
```
timedelta
```
 对象。

 |
```
+t1
```
  | 返回一个相同数值的
```
timedelta
```
 对象。

 |
```
-t1
```
  | 等价于
```
timedelta(-t1.days, -t1.seconds, -t1.microseconds)
```
，以及
```
t1 * -1
```
。 (1)(4)

 |
```
abs(t)
```
  | 当
```
t.days >= 0
```
 时等于
```
+t
```
，而当
```
t.days < 0
```
 时等于
```
-t
```
。 (2)

 |
```
str(t)
```
  | 返回一个形如
```
[D day[s], ][H]H:MM:SS[.UUUUUU]
```
 的字符串，当
```
t
```
 为负数的时候， D 也为负数。 (5)

 |
```
repr(t)
```
  | 返回一个
```
timedelta
```
 对象的字符串表示形式，作为附带正规属性值的构造器调用。

   注释：

1. 结果正确，但可能会溢出。

1. 结果正确，不会溢出。

1. 除以零将会引发
```
ZeroDivisionError
```
。

1.
```
-timedelta.max
```
 不可以表示为一个
```
timedelta
```
 对象。

1.
```
timedelta
```
 对象的字符串表示形式类似于其内部表示形式被规范化。对于负时间增量，这会导致一些不寻常的结果。例如:

```
>>> timedelta(hours=-5)
datetime.timedelta(days=-1, seconds=68400)
>>> print(_)
-1 day, 19:00:00
```

1. 表达式
```
t2 - t3
```
 通常与
```
t2 + (-t3)
```
 是等价的，除非 t3 等于
```
timedelta.max
```
; 在这种情况下前者会返回结果，而后者则会溢出。

 除了上面列举的操作以外，
```
timedelta
```
 对象还支持与
```
date
```
 和
```
datetime
```
 对象进行特定的相加和相减运算（见下文）。
  在 3.2 版本发生变更: 现已支持
```
timedelta
```
 对象与另一个
```
timedelta
```
 对象间的向下取整除法或真除法，包括求余运算和
```
divmod()
```
 函数。
```
timedelta
```
 对象与
```
float
```
 对象间的真除法和乘法现在也已受到支持。

```
timedelta
```
 对象支持相等性和顺序比较。
 在布尔运算中，
```
timedelta
```
 对象当且仅当其不等于
```
timedelta(0)
```
 时则会被视为真值。
 实例方法：
   timedelta.total_seconds()¶
 返回时间区间包含的总秒数。 等价于
```
td / timedelta(seconds=1)
```
。 对于秒以外的间隔单位，可直接使用除法形式 (例如，
```
td / timedelta(microseconds=1)
```
)。
 需要注意的是，时间间隔较大时，这个方法的结果中的微秒将会失真（大多数平台上大于270年视为一个较大的时间间隔）。
  Added in version 3.2.

### 用法示例:
```
timedelta
```
¶
 一个标准化的附加示例:

```
>>> # another_year 的部分增加恰好 365 天
>>> import datetime as dt
>>> year = dt.timedelta(days=365)
>>> another_year = dt.timedelta(weeks=40, days=84, hours=23,
...                             minutes=50, seconds=600)
>>> year == another_year
True
>>> year.total_seconds()
31536000.0
```

```
timedelta
```
 算术运算的示例:

```
>>> import datetime as dt
>>> year = dt.timedelta(days=365)
>>> ten_years = 10 * year
>>> ten_years
datetime.timedelta(days=3650)
>>> ten_years.days // 365
10
>>> nine_years = ten_years - year
>>> nine_years
datetime.timedelta(days=3285)
>>> three_years = nine_years // 3
>>> three_years, three_years.days // 365
(datetime.timedelta(days=1095), 3)
```

##
```
date
```
 对象¶

```
date
```
 对象代表一个理想化历法中的日期（年、月和日），即当今的格列高利历向前后两个方向无限延伸。
 公元 1 年 1 月 1日是第 1 日，公元 1 年 1 月 2 日是第 2 日，依此类推。 [2]
   class datetime.date(year, month, day)¶
 所有参数都是必要的。 参数必须是在下面范围内的整数：

-
```
MINYEAR <= year <= MAXYEAR
```

-
```
1 <= month <= 12
```

-
```
1 <= 日期 <= 给定年月对应的天数
```

 如果参数不在这些范围内，则抛出
```
ValueError
```
 异常。

 其它构造器，所有的类方法：
   classmethod date.today()¶
 返回当前的本地日期。
 这等价于
```
date.fromtimestamp(time.time())
```
。

   classmethod date.fromtimestamp(timestamp)¶
 返回对应于 POSIX 时间戳 的本地时间，例如
```
time.time()
```
 所返回的值。
 这可能引发
```
OverflowError
```
，如果时间戳数值超出所在平台 C
```
localtime()
```
 函数的支持范围的话，并且会在
```
localtime()
```
 出错时引发
```
OSError
```
。 通常该数值会被限制在 1970 年至 2038 年之间。 请注意在时间戳概念包含闰秒的非 POSIX 系统上，闰秒会被
```
fromtimestamp()
```
 所忽略。
  在 3.3 版本发生变更: 引发
```
OverflowError
```
 而不是
```
ValueError
```
，如果时间戳数值超出所在平台 C
```
localtime()
```
 函数的支持范围的话，并会在
```
localtime()
```
 出错时引发
```
OSError
```
 而不是
```
ValueError
```
。

   classmethod date.fromordinal(ordinal)¶
 返回对应于格列高利历 序号 的日期，其中公元 1 年 1 月 1 日的序号为 1。
 除非
```
1 <= ordinal <= date.max.toordinal()
```
 否则会引发
```
ValueError
```
。 对于任意的日期
```
d
```
，均有
```
date.fromordinal(d.toordinal()) == d
```
。

   classmethod date.fromisoformat(date_string)¶
 返回一个对应于以任何有效 ISO 8601 格式给出的 date_string 的
```
date
```
，下列格式除外：

1. 目前不支持降低精度的日期 (
```
YYYY-MM
```
,
```
YYYY
```
)。

1. 目前不支持扩展日期表示形式 (
```
±YYYYYY-MM-DD
```
)。

1. 目前不支持序数日期 (
```
YYYY-OOO
```
)。

 示例:

```
>>> import datetime as dt
>>> dt.date.fromisoformat('2019-12-04')
datetime.date(2019, 12, 4)
>>> dt.date.fromisoformat('20191204')
datetime.date(2019, 12, 4)
>>> dt.date.fromisoformat('2021-W01-1')
datetime.date(2021, 1, 4)
```

  Added in version 3.7.

  在 3.11 版本发生变更: 在之前版本中，此方法仅支持一种格式
```
YYYY-MM-DD
```
。

   classmethod date.fromisocalendar(year, week, day)¶
 返回对应于由 year, week 和 day 指定的 ISO 历法日期的
```
date
```
。 这是函数
```
date.isocalendar()
```
 的逆操作。
  Added in version 3.8.

   classmethod date.strptime(date_string, format)¶
 返回一个对应于 date_string，根据 format 进行解析得到的
```
date
```
。 这等价于:

```
date(*(time.strptime(date_string, format)[0:3]))
```

 如果 date_string 和 format 无法被
```
time.strptime()
```
 解析或它返回一个不是时间元组的值则将引发
```
ValueError
```
。 另请参阅 strftime() 和 strptime() 的行为 和
```
date.fromisoformat()
```
。
  备注
 If format specifies a day of month without a year a
```
DeprecationWarning
```
 is emitted. This is to avoid a quadrennial leap year bug in code seeking to parse only a month and day as the default year used in absence of one in the format is not a leap year. Such format values may raise an error as of Python 3.15. The workaround is to always include a year in your format. If parsing date_string values that do not have a year, explicitly add a year that is a leap year before parsing:

```
>>> import datetime as dt
>>> date_string = "02/29"
>>> when = dt.date.strptime(f"{date_string};1984", "%m/%d;%Y")  # 避免闰年 BUG。
>>> when.strftime("%B %d")
'February 29'
```

  Added in version 3.14.

 类属性：
   date.min¶
 最小的日期
```
date(MINYEAR, 1, 1)
```
 。

   date.max¶
 最大的日期 ，
```
date(MAXYEAR, 12, 31)
```
。

   date.resolution¶
 两个日期对象的最小间隔，
```
timedelta(days=1)
```
。

 实例属性（只读）：
   date.year¶
 在
```
MINYEAR
```
 和
```
MAXYEAR
```
 之间，包含边界。

   date.month¶
 1 至 12（含）

   date.day¶
 返回1到指定年月的天数间的数字。

 支持的运算：

运算
 结果：

 |
```
date2 = date1 + timedelta
```
  |
```
date2
```
 将为
```
date1
```
 之后的
```
timedelta.days
```
 日。 (1)

 |
```
date2 = date1 - timedelta
```
  | 计算
```
date2
```
 使得
```
date2 + timedelta == date1
```
。 (2)

 |
```
timedelta = date1 - date2
```
  | (3)

 |
```
date1 == date2
```

```
date1 != date2
```

   | 相等性比较。 (4)

 |
```
date1 < date2
```

```
date1 > date2
```

```
date1 <= date2
```

```
date1 >= date2
```

   | 顺序比较。 (5)

   注释：

1. 如果
```
timedelta.days > 0
```
 则 date2 将在时间线上前进，如果
```
timedelta.days < 0
```
 则将后退。 操作完成后
```
date2 - date1 == timedelta.days
```
。
```
timedelta.seconds
```
 和
```
timedelta.microseconds
```
 会被忽略。 如果
```
date2.year
```
 将小于
```
MINYEAR
```
 或大于
```
MAXYEAR
```
 则会引发
```
OverflowError
```
。

1.
```
timedelta.seconds
```
 和
```
timedelta.microseconds
```
 会被忽略。

1. 该值是精确的，且不会溢出。 运算后
```
timedelta.seconds
```
 和
```
timedelta.microseconds
```
 均为 0，且
```
date2 + timedelta == date1
```
。

1.
```
date
```
 对象在表示相同的日期时相等。
 不属于
```
datetime
```
 实例的
```
date
```
 对象永远不会与
```
datetime
```
 对象相等，即使它们表示相同的日期。

1. 当 date1 的时间在 date2 之前则认为 date1 小于 date2。 换句话说，当且仅当
```
date1.toordinal() < date2.toordinal()
```
 时
```
date1 < date2
```
。
 不同时为
```
datetime
```
 实例的
```
date
```
 对象和
```
datetime
```
 对象之间的顺序比较将会引发
```
TypeError
```
。

  在 3.13 版本发生变更: 在
```
datetime
```
 对象和不属于
```
datetime
```
 子类的
```
date
```
 子类的实例之间进行比较时不会再将后者转换为
```
date
```
，并忽略时间部分和时区信息。 此默认行为可以通过在子类中重写特殊比较方法来更改。

 在布尔运算中，所有
```
date
```
 对象都会被视为真值。
 实例方法：
   date.replace(year=self.year, month=self.month, day=self.day)¶
 返回一个具有同样的值，但更新了指定形参的新的
```
date
```
 对象。
 示例:

```
>>> import datetime as dt
>>> d = dt.date(2002, 12, 31)
>>> d.replace(day=26)
datetime.date(2002, 12, 26)
```

 泛型函数
```
copy.replace()
```
 也支持
```
date
```
 对象。

   date.timetuple()¶
 返回一个
```
time.struct_time
```
，即
```
time.localtime()
```
 所返回的类型。
 hours, minutes 和 seconds 值均为 0，且 DST 旗标值为 -1。

```
d.timetuple()
```
 等价于:

```
time.struct_time((d.year, d.month, d.day, 0, 0, 0, d.weekday(), yday, -1))
```

 其中
```
yday = d.toordinal() - date(d.year, 1, 1).toordinal() + 1
```
 是当前年份中的日期序号，起始值 1 表示 1 月 1 日。

   date.toordinal()¶
 返回日期的预期格列高利历序号，其中公元 1 年 1 月 1 日的序号为 1. 对于任意的
```
date
```
 对象
```
d
```
，均有
```
date.fromordinal(d.toordinal()) == d
```
。

   date.weekday()¶
 返回一个整数代表星期几，星期一为0，星期天为6。例如，
```
date(2002, 12, 4).weekday() == 2
```
，表示的是星期三。参阅
```
isoweekday()
```
。

   date.isoweekday()¶
 返回一个整数代表星期几，星期一为 1，星期天为 7。 例如:
```
date(2002, 12, 4).isoweekday() == 3
```
 表示星期三。 参见
```
weekday()
```
,
```
isocalendar()
```
。

   date.isocalendar()¶
 返回一个由三部分组成的 named tuple 对象:
```
year
```
,
```
week
```
 和
```
weekday
```
。
 ISO 历法是一种被广泛使用的格列高利历。 [3]
 ISO 年由 52 或 53 个完整星期构成，每个星期开始于星期一结束于星期日。 一个 ISO 年的第一个星期就是（格列高利）历法的一年中第一个包含星期四的星期。 这被称为 1 号星期，这个星期四所在的 ISO 年与其所在的格列高利年相同。
 例如，2004 年的第一天是星期四，因此 ISO 2004 年的第一个星期开始于 2003 年 12 月 29 日星期一，结束于 2004 年 1 月 4 日星期日:

```
>>> import datetime as dt
>>> dt.date(2003, 12, 29).isocalendar()
datetime.IsoCalendarDate(year=2004, week=1, weekday=1)
>>> dt.date(2004, 1, 4).isocalendar()
datetime.IsoCalendarDate(year=2004, week=1, weekday=7)
```

  在 3.9 版本发生变更: 结果由元组改为 named tuple。

   date.isoformat()¶
 返回一个以 ISO 8601 格式
```
YYYY-MM-DD
```
 来表示日期的字符串:

```
>>> import datetime as dt
>>> dt.date(2002, 12, 4).isoformat()
'2002-12-04'
```

   date.__str__()¶
 对于日期
```
d
```
，
```
str(d)
```
 等价于
```
d.isoformat()
```
。

   date.ctime()¶
 返回一个表示日期的字符串:

```
>>> import datetime as dt
>>> dt.date(2002, 12, 4).ctime()
'Wed Dec  4 00:00:00 2002'
```

```
d.ctime()
```
 等效于:

```
time.ctime(time.mktime(d.timetuple()))
```

 在原生 C
```
ctime()
```
 函数遵循 C 标准的平台上 (
```
time.ctime()
```
 会发起对该函数的调用，但
```
date.ctime()
```
 并不会) 。

   date.strftime(format)¶
 返回一个由显式格式字符串所控制的，代表日期的字符串。 表示时、分或秒的格式代码值将为 0。 另请参阅 strftime() 和 strptime() 的行为 和
```
date.isoformat()
```
。

   date.__format__(format)¶
 与
```
date.strftime()
```
 相同。 此方法使得在 格式化字符串字面值 中以及使用
```
str.format()
```
 时为
```
date
```
 对象指定格式字符串成为可能。 另请参阅 strftime() 和 strptime() 的行为 和
```
date.isoformat()
```
。

### 用法示例:
```
date
```
¶
 计算距离特定事件天数的例子:

```
>>> import time
>>> import datetime as dt
>>> today = dt.date.today()
>>> today
datetime.date(2007, 12, 5)
>>> today == dt.date.fromtimestamp(time.time())
True
>>> my_birthday = dt.date(today.year, 6, 24)
>>> if my_birthday < today:
...     my_birthday = my_birthday.replace(year=today.year + 1)
...
>>> my_birthday
datetime.date(2008, 6, 24)
>>> time_to_birthday = abs(my_birthday - today)
>>> time_to_birthday.days
202
```

 使用
```
date
```
 的更多例子：

```
>>> import datetime as dt
>>> d = dt.date.fromordinal(730920) # # 1. 1. 0001 之后的第 730920 天
>>> d
datetime.date(2002, 3, 11)

>>> # 有关格式化字符串输出的方法
>>> d.isoformat()
'2002-03-11'
>>> d.strftime("%d/%m/%y")
'11/03/02'
>>> d.strftime("%A %d. %B %Y")
'Monday 11. March 2002'
>>> d.ctime()
'Mon Mar 11 00:00:00 2002'
>>> 'The {1} is {0:%d}, the {2} is {0:%B}.'.format(d, "day", "month")
'The day is 11, the month is March.'

>>> # 用于提取不同历法中的‘部分’的方法
>>> t = d.timetuple()
>>> for i in t:
...     print(i)
2002                # 年
3                   # 月
11                  # 日
0
0
0
0                   # 周序号 (0 = 星期一)
70                  # 当年的第 70 天
-1
>>> ic = d.isocalendar()
>>> for i in ic:
...     print(i)
2002                # ISO 年
11                  # ISO 第几周
1                   # ISO 周序号 ( 1 = 星期一 )

>>> # 日期对象是不可变的；所有操作都将产生一个新对象
>>> d.replace(year=2005)
datetime.date(2005, 3, 11)
```

##
```
datetime
```
 对象¶

```
datetime
```
 对象是包含来自
```
date
```
 对象和
```
time
```
 对象的所有信息的单一对象。
 与
```
date
```
 对象类似，
```
datetime
```
 假定当前的格列高利历向前后两个方向无限延伸；与
```
time
```
 对象类似，
```
datetime
```
 假定每一天恰好有 3600*24 秒。
 构造器 ：
   class datetime.datetime(year, month, day, hour=0, minute=0, second=0, microsecond=0, tzinfo=None, *, fold=0)¶
 year, month 和 day 参数是必须的。 tzinfo 可以是
```
None
```
 或者是一个
```
tzinfo
```
 子类的实例。 其余的参数必须是在下面范围内的整数：

-
```
MINYEAR <= year <= MAXYEAR
```
,

-
```
1 <= month <= 12
```
,

-
```
1 <= day <= 指定年月的天数
```
,

-
```
0 <= hour < 24
```
,

-
```
0 <= minute < 60
```
,

-
```
0 <= second < 60
```
,

-
```
0 <= microsecond < 1000000
```
,

-
```
fold in [0, 1]
```
.

 如果参数不在这些范围内，则抛出
```
ValueError
```
 异常。
  在 3.6 版本发生变更: 增加了 fold 形参。

 其它构造器，所有的类方法：
   classmethod datetime.today()¶
 返回表示当前地方时的 date 和 time，其中
```
tzinfo
```
 为
```
None
```
。
 等价于:

```
datetime.fromtimestamp(time.time())
```

 另请参阅
```
now()
```
,
```
fromtimestamp()
```
。
 此方法的功能等价于
```
now()
```
，但是不带
```
tz
```
 形参。

   classmethod datetime.now(tz=None)¶
 返回表示当前地方时的 date 和 time 对象。
 如果可选参数 tz 为
```
None
```
 或未指定，这就类似于
```
today()
```
，但该方法会在可能的情况下提供比通过
```
time.time()
```
 时间戳所获时间值更高的精度（例如，在提供了 C
```
gettimeofday()
```
 函数的平台上就可以做到这一点）。
 如果 tz 不为
```
None
```
，它必须是
```
tzinfo
```
 子类的一个实例，并且当前日期和时间将被转换到 tz 时区。
 此函数可以替代
```
today()
```
 和
```
utcnow()
```
。
  备注
 对
```
datetime.now()
```
 的后续调用可能由于下层时钟的精度返回相同的时刻。

   classmethod datetime.utcnow()¶
 返回表示当前 UTC 时间的 date 和 time，其中
```
tzinfo
```
 为
```
None
```
。
 这类似于
```
now()
```
，但返回的是当前 UTC 日期和时间，类型为简单型
```
datetime
```
 对象。 感知型的当前 UTC 日期时间可通过调用
```
datetime.now(timezone.utc)
```
 来获得。 另请参阅
```
now()
```
。
  警告
 由于简单型
```
datetime
```
 对象会被许多
```
datetime
```
 方法当作本地时间来处理，最好是使用感知型日期时间对象来表示 UTC 时间。 因此，创建表示当前 UTC 时间的对象的推荐方式是通过调用
```
datetime.now(timezone.utc)
```
。

  自 3.12 版本弃用: 改用带
```
UTC
```
 的
```
datetime.now()
```
。

   classmethod datetime.fromtimestamp(timestamp, tz=None)¶
 返回 POSIX 时间戳对应的本地日期和时间，如
```
time.time()
```
 返回的。 如果可选参数 tz 指定为
```
None
```
 或未指定，时间戳将转换为平台的本地日期和时间，并且返回的
```
datetime
```
 对象将为简单型。
 如果 tz 不为
```
None
```
，它必须是
```
tzinfo
```
 子类的一个实例，并且时间戳将被转换到 tz 指定的时区。

```
fromtimestamp()
```
 可能会引发
```
OverflowError
```
，如果时间戳数值超出所在平台 C
```
localtime()
```
 或
```
gmtime()
```
 函数的支持范围的话，并会在
```
localtime()
```
 或
```
gmtime()
```
 报错时引发
```
OSError
```
。 通常该数值会被限制在 1970 年至 2038 年之间。 请注意在时间戳概念包含闰秒的非 POSIX 系统上，闰秒会被
```
fromtimestamp()
```
 所忽略，结果可能导致两个相差一秒的时间戳产生相同的
```
datetime
```
 对象。 相比
```
utcfromtimestamp()
```
 更推荐使用此方法。
  在 3.3 版本发生变更: 引发
```
OverflowError
```
 而不是
```
ValueError
```
，如果时间戳数值超出所在平台 C
```
localtime()
```
 或
```
gmtime()
```
 函数的支持范围的话。 并会在
```
localtime()
```
 或
```
gmtime()
```
 出错时引发
```
OSError
```
 而不是
```
ValueError
```
。

  在 3.6 版本发生变更:
```
fromtimestamp()
```
 可能返回
```
fold
```
 值设为 1 的实例。

   classmethod datetime.utcfromtimestamp(timestamp)¶
 返回对应于 POSIX 时间戳的 UTC
```
datetime
```
，其中
```
tzinfo
```
 值为
```
None
```
。 （结果为简单型对象。）
 这可能引发
```
OverflowError
```
，如果时间戳数值超出所在平台 C
```
gmtime()
```
 函数的支持范围的话，并会在
```
gmtime()
```
 报错时引发
```
OSError
```
。 通常该数值会被限制在 1970 至 2038 年之间。
 要得到一个感知型
```
datetime
```
 对象，应调用
```
fromtimestamp()
```
:

```
datetime.fromtimestamp(timestamp, timezone.utc)
```

 在 POSIX 兼容的平台上，它等价于以下表达式:

```
datetime(1970, 1, 1, tzinfo=timezone.utc) + timedelta(seconds=timestamp)
```

 不同之处在于后一种形式总是支持完整年份范围：从
```
MINYEAR
```
 到
```
MAXYEAR
```
 的闭区间。
  警告
 由于简单型
```
datetime
```
 对象会被许多
```
datetime
```
 方法当作本地时间来处理，最好是使用感知型日期时间对象来表示 UTC 时间。 因此，创建表示特定 UTC 时间戳的日期时间对象的推荐方式是通过调用
```
datetime.fromtimestamp(timestamp, tz=timezone.utc)
```
。

  在 3.3 版本发生变更: 引发
```
OverflowError
```
 而不是
```
ValueError
```
，如果时间戳数值超出所在平台 C
```
gmtime()
```
 函数的支持范围的话。 并会在
```
gmtime()
```
 出错时引发
```
OSError
```
 而不是
```
ValueError
```
。

  在 3.15 版本发生变更: 接受任何实数作为 timestamp，而不是只接受整数或浮点数。

  自 3.12 版本弃用: 改用带
```
UTC
```
 的
```
datetime.fromtimestamp()
```
。

   classmethod datetime.fromordinal(ordinal)¶
 返回对应于预期格列高利历序号的
```
datetime
```
，其中公元 1 年 1 月 1 日的序号为 1。 除非
```
1 <= ordinal <= datetime.max.toordinal()
```
 否则会引发
```
ValueError
```
。 结果的 hour, minute, second 和 microsecond 值均为 0，并且
```
tzinfo
```
 值为
```
None
```
。

   classmethod datetime.combine(date, time, tzinfo=time.tzinfo)¶
 返回一个新的
```
datetime
```
 对象，其日期部分等于给定的
```
date
```
 对象的值，而其时间部分等于给定的
```
time
```
 对象的值。 如果提供了 tzinfo 参数，其值会被用来设置结果的
```
tzinfo
```
 属性，否则将使用 time 参数的
```
tzinfo
```
 属性。 如果 date 参数是一个
```
datetime
```
 对象，其时间部分和
```
tzinfo
```
 属性将被忽略。
 对于任意
```
datetime
```
 对象
```
d
```
，
```
d == datetime.combine(d.date(), d.time(), d.tzinfo)
```
。
  在 3.6 版本发生变更: 增加了 tzinfo 参数。

   classmethod datetime.fromisoformat(date_string)¶
 返回一个对应于以任何有效的 ISO 8601 格式给出的 date_string 的
```
datetime
```
，下列格式除外:

1. 时区时差可能会有带小数的秒值。

1.
```
T
```
 分隔符可以用任何单个 unicode 字符来替换。

1. 带小数的时和分是不受支持的。

1. 目前不支持降低精度的日期 (
```
YYYY-MM
```
,
```
YYYY
```
)。

1. 目前不支持扩展日期表示形式 (
```
±YYYYYY-MM-DD
```
)。

1. 目前不支持序数日期 (
```
YYYY-OOO
```
)。

 示例:

```
>>> import datetime as dt
>>> dt.datetime.fromisoformat('2011-11-04')
datetime.datetime(2011, 11, 4, 0, 0)
>>> dt.datetime.fromisoformat('20111104')
datetime.datetime(2011, 11, 4, 0, 0)
>>> dt.datetime.fromisoformat('2011-11-04T00:05:23')
datetime.datetime(2011, 11, 4, 0, 5, 23)
>>> dt.datetime.fromisoformat('2011-11-04T00:05:23Z')
datetime.datetime(2011, 11, 4, 0, 5, 23, tzinfo=datetime.timezone.utc)
>>> dt.datetime.fromisoformat('20111104T000523')
datetime.datetime(2011, 11, 4, 0, 5, 23)
>>> dt.datetime.fromisoformat('2011-W01-2T00:05:23.283')
datetime.datetime(2011, 1, 4, 0, 5, 23, 283000)
>>> dt.datetime.fromisoformat('2011-11-04 00:05:23.283')
datetime.datetime(2011, 11, 4, 0, 5, 23, 283000)
>>> dt.datetime.fromisoformat('2011-11-04 00:05:23.283+00:00')
datetime.datetime(2011, 11, 4, 0, 5, 23, 283000, tzinfo=datetime.timezone.utc)
>>> dt.datetime.fromisoformat('2011-11-04T00:05:23+04:00')
datetime.datetime(2011, 11, 4, 0, 5, 23,
    tzinfo=datetime.timezone(datetime.timedelta(seconds=14400)))
```

  Added in version 3.7.

  在 3.11 版本发生变更: 在之前版本中，此方法仅支持可以由
```
date.isoformat()
```
 或
```
datetime.isoformat()
```
 发出的格式。

   classmethod datetime.fromisocalendar(year, week, day)¶
 返回一个
```
datetime
```
，其值对应于由 year, week 和 day 指明的 ISO 历法日期。 该 datetime 对象的非日期部分将使用其标准默认值来填充。 这是函数
```
datetime.isocalendar()
```
 的逆操作。
  Added in version 3.8.

   classmethod datetime.strptime(date_string, format)¶
 返回一个对应于 date_string，根据 format 进行解析得到的
```
datetime
```
 对象。
 如果 format 不包含微秒或时区信息，这将等价于:

```
datetime(*(time.strptime(date_string, format)[0:6]))
```

 如果 date_string 和 format 无法被
```
time.strptime()
```
 解析或它返回一个不是时间元组的值则将引发
```
ValueError
```
。 另请参阅 strftime() 和 strptime() 的行为 和
```
datetime.fromisoformat()
```
。
  在 3.13 版本发生变更: If format specifies a day of month without a year a
```
DeprecationWarning
```
 is now emitted. This is to avoid a quadrennial leap year bug in code seeking to parse only a month and day as the default year used in absence of one in the format is not a leap year. Such format values may raise an error as of Python 3.15. The workaround is to always include a year in your format. If parsing date_string values that do not have a year, explicitly add a year that is a leap year before parsing:

```
>>> import datetime as dt
>>> date_string = "02/29"
>>> when = dt.datetime.strptime(f"{date_string};1984", "%m/%d;%Y")  # 避免闰年 BUG。
>>> when.strftime("%B %d")
'February 29'
```

 类属性：
   datetime.min¶
 最早的可表示
```
datetime
```
，
```
datetime(MINYEAR, 1, 1, tzinfo=None)
```
。

   datetime.max¶
 最晚的可表示
```
datetime
```
，
```
datetime(MAXYEAR, 12, 31, 23, 59, 59, 999999, tzinfo=None)
```
。

   datetime.resolution¶
 两个不相等的
```
datetime
```
 对象之间可能的最小间隔，
```
timedelta(microseconds=1)
```
。

 实例属性（只读）：
   datetime.year¶
 在
```
MINYEAR
```
 和
```
MAXYEAR
```
 之间，包含边界。

   datetime.month¶
 1 至 12（含）

   datetime.day¶
 返回1到指定年月的天数间的数字。

   datetime.hour¶
 取值范围是
```
range(24)
```
。

   datetime.minute¶
 取值范围是
```
range(60)
```
。

   datetime.second¶
 取值范围是
```
range(60)
```
。

   datetime.microsecond¶
 取值范围是
```
range(1000000)
```
。

   datetime.tzinfo¶
 作为 tzinfo 参数被传给
```
datetime
```
 构造器的对象，如果没有传入值则为
```
None
```
。

   datetime.fold¶
 取值范围是
```
[0, 1]
```
。 用于在重复的时间段中消除边界时间的歧义。 （当夏令时结束时回拨时钟或由于政治原因导致当前时区的 UTC 时差减少就会出现重复时间段。） 取值 0 和 1 分别表示两个相同边界时间表示形式的前一个和后一个时间。
  Added in version 3.6.

 支持的运算：

运算
 结果：

 |
```
datetime2 = datetime1 + timedelta
```
  | (1)

 |
```
datetime2 = datetime1 - timedelta
```
  | (2)

 |
```
timedelta = datetime1 - datetime2
```
  | (3)

 |
```
datetime1 == datetime2
```

```
datetime1 != datetime2
```

   | 相等性比较。 (4)

 |
```
datetime1 < datetime2
```

```
datetime1 > datetime2
```

```
datetime1 <= datetime2
```

```
datetime1 >= datetime2
```

   | 顺序比较。 (5)

1.
```
datetime2
```
 是
```
datetime1
```
 去掉
```
timedelta
```
 时间段的结果，如果
```
timedelta.days > 0
```
 则是在时间线上前进，如果
```
timedelta.days < 0
```
 则时在时间线上后退。 该结果具有与输入的 datetime 相同的
```
tzinfo
```
 属性，并且运算后
```
datetime2 - datetime1 == timedelta
```
。 如果
```
datetime2.year
```
 将要小于
```
MINYEAR
```
 或大于
```
MAXYEAR
```
 则会引发
```
OverflowError
```
。 请注意即使输入的是一个感知型对象该方法也不会进行时区调整。

1. 计算
```
datetime2
```
 使得
```
datetime2 + timedelta == datetime1
```
。 与相加操作一样，结果具有与输入的 datetime 相同的
```
tzinfo
```
 属性，即使输入的是一个感知型对象该方法也不会进行时区调整。

1. 从一个
```
datetime
```
 减去一个
```
datetime
```
 仅在两个操作数均为简单型，或是均为感知型时有定义。 如果一个是感知型而另一个是简单型，则会引发
```
TypeError
```
。
 如果两个操作数都是简单型，或都是感知型并且具有相同的
```
tzinfo
```
 属性，则
```
tzinfo
```
 属性会被忽略，并且结果会是一个使得
```
datetime2 + t == datetime1
```
 的
```
timedelta
```
 对象
```
t
```
。 在此情况下不会进行时区调整。
 如果两者均为感知型且具有不同的
```
tzinfo
```
 属性，
```
a-b
```
 的效果就如同
```
a
```
 和
```
b
```
 首先被转换为简单型 UTC 日期时间。 结果将为
```
(a.replace(tzinfo=None) - a.utcoffset()) - (b.replace(tzinfo=None) - b.utcoffset())
```
，不同之处在于具体实现绝对不会溢出。

1.
```
datetime
```
 对象如果在考虑时区的情况下表示相同的日期和时间那么就是相等的。
 简单型和感知型
```
datetime
```
 对象绝不会相等。
 如果两个比较操作数均为感知型，且具有相同的
```
tzinfo
```
 属性，则
```
tzinfo
```
 和
```
fold
```
 属性将被忽略并对基本日期时间值进行比较。 如果两个比较操作数均为感知型且具有不同的
```
tzinfo
```
 属性，则比较行为将如同两个操作数首先被转换为 UTC，不同之处是具体实现绝对不会溢出。 具有重复间隔的
```
datetime
```
 实例绝对不会等于属于其他时区的
```
datetime
```
 实例。

1. 在考虑时区的情况下，当 datetime1 的时间在 datetime2 之前则认为 datetime1 小于 datetime2。
 简单型和感知型
```
datetime
```
 对象之间的顺序比较将会引发
```
TypeError
```
。
 如果两个操作数均为感知型，且具有相同的
```
tzinfo
```
 属性，则
```
tzinfo
```
 和
```
fold
```
 属性将被忽略并对基本日期时间值进行比较。 如果两个操作数均为感知型且具有不同的
```
tzinfo
```
 属性，则比较行为将如同两个操作数首先被转换为 UTC 日期时间，不同之处是具体实现绝对不会溢出。

  在 3.3 版本发生变更: 感知型和简单型
```
datetime
```
 实例之间的相等比较不会引发
```
TypeError
```
。

  在 3.13 版本发生变更: 在
```
datetime
```
 对象和不属于
```
datetime
```
 子类的
```
date
```
 子类的实例之间进行比较时不会再将后者转换为
```
date
```
，并忽略时间部分和时区信息。 此默认行为可以通过在子类中重写特殊比较方法来更改。

 实例方法：
   datetime.date()¶
 返回具有同样 year, month 和 day 值的
```
date
```
 对象。

   datetime.time()¶
 返回具有同样 hour, minute, second, microsecond 和 fold 值的
```
time
```
 对象。
```
tzinfo
```
 值为
```
None
```
。 另请参见
```
timetz()
```
 方法。
  在 3.6 版本发生变更: fold 值会被复制给返回的
```
time
```
 对象。

   datetime.timetz()¶
 返回具有同样 hour, minute, second, microsecond, fold 和 tzinfo 属性的
```
time
```
 对象。 另请参见
```
time()
```
 方法。
  在 3.6 版本发生变更: fold 值会被复制给返回的
```
time
```
 对象。

   datetime.replace(year=self.year, month=self.month, day=self.day, hour=self.hour, minute=self.minute, second=self.second, microsecond=self.microsecond, tzinfo=self.tzinfo, *, fold=0)¶
 返回一个具有同样属性的新的
```
datetime
```
 对象，但更新指定的形参。 请注意可以通过指定
```
tzinfo=None
```
 基于一个感知型 datetime 创建一个简单型 datetime 而不必转换日期和时间数据。

```
datetime
```
 对象也被泛型函数
```
copy.replace()
```
 所支持。
  在 3.6 版本发生变更: 增加了 fold 形参。

   datetime.astimezone(tz=None)¶
 返回一个具有新的
```
tzinfo
```
 属性 tz 的
```
datetime
```
 对象，并会调整日期和时间数据使得结果对应的 UTC 时间与 self 相同，但为 tz 时区的本地时间。
 如果给出了 tz，则它必须是一个
```
tzinfo
```
 子类的实例，并且其
```
utcoffset()
```
 和
```
dst()
```
 方法不可返回
```
None
```
。 如果 self 为简单型，它会被假定为基于系统时区表示的时间。
 如果调用时不传入参数 (或传入
```
tz=None
```
) 则将假定目标时区为系统的本地时区。 转换后 datetime 实例的
```
.tzinfo
```
 属性将被设为一个
```
timezone
```
 实例，时区名称和时差值将从 OS 获取。
 如果
```
self.tzinfo
```
 为 tz，
```
self.astimezone(tz)
```
 等于 self: 不会对日期或时间数据进行调整。 否则结果为 tz 时区的本地时间，代表的 UTC 时间与 self 相同：在
```
astz = dt.astimezone(tz)
```
 之后，
```
astz - astz.utcoffset()
```
 将具有与
```
dt - dt.utcoffset()
```
 相同的日期和时间数据。
 如果你只是想要附加一个
```
timezone
```
 对象 tz 到一个 datetime 对象 dt 而不调整日期和时间数据，请使用
```
dt.replace(tzinfo=tz)
```
。 如果你只是想要从一个感知型 datetime 对象 dt 移除
```
timezone
```
 对象，请使用
```
dt.replace(tzinfo=None)
```
。
 请注意默认的
```
tzinfo.fromutc()
```
 方法在
```
tzinfo
```
 的子类中可以被重写，从而影响
```
astimezone()
```
 的返回结果。 如果忽略出错的情况，
```
astimezone()
```
 的行为就类似于:

```
def astimezone(self, tz):
    if self.tzinfo is tz:
        return self
    # 将 self 转换为 UTC，并附加新的时区对象
    utc = (self - self.utcoffset()).replace(tzinfo=tz)
    # 从 UTC 转换为 tz 的地方时。
    return tz.fromutc(utc)
```

  在 3.3 版本发生变更: tz 现在可以被省略。

  在 3.6 版本发生变更:
```
astimezone()
```
 方法可以由简单型实例调用，这将假定其表示本地时间。

   datetime.utcoffset()¶
 如果
```
tzinfo
```
 为
```
None
```
，则返回
```
None
```
，否则返回
```
self.tzinfo.utcoffset(self)
```
，并且在后者不返回
```
None
```
 或者一个幅度小于一天的
```
timedelta
```
 对象时将引发异常。
  在 3.7 版本发生变更: UTC 时差不再限制为一个整数分钟值。

   datetime.dst()¶
 如果
```
tzinfo
```
 为
```
None
```
，则返回
```
None
```
，否则返回
```
self.tzinfo.dst(self)
```
，并且在后者不返回
```
None
```
 或者一个幅度小于一天的
```
timedelta
```
 对象时将引发异常。
  在 3.7 版本发生变更: DST 差值不再限制为一个整数分钟值。

   datetime.tzname()¶
 如果
```
tzinfo
```
 为
```
None
```
，则返回
```
None
```
，否则返回
```
self.tzinfo.tzname(self)
```
，如果后者不返回
```
None
```
 或者一个字符串对象则将引发异常。

   datetime.timetuple()¶
 返回一个
```
time.struct_time
```
，即
```
time.localtime()
```
 所返回的类型。

```
d.timetuple()
```
 等价于:

```
time.struct_time((d.year, d.month, d.day,
                  d.hour, d.minute, d.second,
                  d.weekday(), yday, dst))
```

 其中
```
yday = d.toordinal() - date(d.year, 1, 1).toordinal() + 1
```
 是日期在当前年份中的序号，起始值 1 表示 1 月 1 日。 结果的
```
tm_isdst
```
 旗标会根据
```
dst()
```
 方法来设定：如果
```
tzinfo
```
 为
```
None
```
 或
```
dst()
```
 返回
```
None
```
，则
```
tm_isdst
```
 将设为
```
-1
```
；否则如果
```
dst()
```
 返回非零值，则
```
tm_isdst
```
 将设为 1；在其他情况下
```
tm_isdst
```
 将设为 0。

   datetime.utctimetuple()¶
 如果
```
datetime
```
 实例
```
d
```
 为简单型，这将与
```
d.timetuple()
```
 相当，区别在于
```
tm_isdst
```
 会被强制设为 0 而无视
```
d.dst()
```
 返回值。 DST 对于 UTC 时间必定无效。
 如果
```
d
```
 为感知型，则
```
d
```
 会通过减去
```
d.utcoffset()
```
 来标准化为 UTC 时间，并返回表示该标准化时间的
```
time.struct_time
```
。
```
tm_isdst
```
 将被强制设为 0。 请注意如果
```
d.year
```
 为
```
MINYEAR
```
 或
```
MAXYEAR
```
 且 UTC 调整超出一年的边界则可能引发
```
OverflowError
```
。
  警告
 由于简单型
```
datetime
```
 对象会被许多
```
datetime
```
 方法当作本地时间来处理，最好是使用感知型日期时间来表示 UTC 时间；因此，使用
```
datetime.utctimetuple()
```
 可能会给出误导性的结果。 如果你有一个表示 UTC 的简单型
```
datetime
```
，请使用
```
datetime.replace(tzinfo=timezone.utc)
```
 将其改为感知型，这样你才能使用
```
datetime.timetuple()
```
。

   datetime.toordinal()¶
 返回日期的预期格列高利历序号。 与
```
self.date().toordinal()
```
 相同。

   datetime.timestamp()¶
 返回对应于
```
datetime
```
 实例的 POSIX 时间戳。 此返回值是与
```
time.time()
```
 返回值类似的
```
float
```
 对象。
 Naive
```
datetime
```
 instances are assumed to represent local time and this method relies on the platform C
```
mktime()
```
 function to perform the conversion. Since
```
datetime
```
 supports wider range of values than
```
mktime()
```
 on many platforms, this method may raise
```
OverflowError
```
 or
```
OSError
```
 for times far in the past or far in the future.
 对于感知型
```
datetime
```
 实例，返回值的计算方式为:

```
(dt - datetime(1970, 1, 1, tzinfo=timezone.utc)).total_seconds()
```

  备注
 没有一个方法能直接从表示 UTC 时间的简单型
```
datetime
```
 实例获取 POSIX 时间戳。 如果你的应用程序使用此惯例并且你的系统时区不是设为 UTC，你可以通过提供
```
tzinfo=timezone.utc
```
 来获取 POSIX 时间戳:

```
timestamp = dt.replace(tzinfo=timezone.utc).timestamp()
```

 或者通过直接计算时间戳:

```
timestamp = (dt - datetime(1970, 1, 1)) / timedelta(seconds=1)
```

  Added in version 3.3.

  在 3.6 版本发生变更:
```
timestamp()
```
 方法使用
```
fold
```
 属性来消除重复间隔中的时间歧义。

   datetime.weekday()¶
 返回一个整数代表星期几，星期一为 0，星期天为 6。 相当于
```
self.date().weekday()
```
。 另请参阅
```
isoweekday()
```
。

   datetime.isoweekday()¶
 返回一个整数代表星期几，星期一为 1，星期天为 7。 相当于
```
self.date().isoweekday()
```
。 另请参阅
```
weekday()
```
,
```
isocalendar()
```
。

   datetime.isocalendar()¶
 返回一个由三部分组成的 named tuple:
```
year
```
,
```
week
```
 和
```
weekday
```
。 等同于
```
self.date().isocalendar()
```
。

   datetime.isoformat(sep='T', timespec='auto')¶
 返回一个以 ISO 8601 格式表示的日期和时间字符串：

-
```
YYYY-MM-DDTHH:MM:SS.ffffff
```
，如果
```
microsecond
```
 不为 0

-
```
YYYY-MM-DDTHH:MM:SS
```
，如果
```
microsecond
```
 为 0

 如果
```
utcoffset()
```
 返回值不为
```
None
```
，则添加一个字符串来给出 UTC 时差：

-
```
YYYY-MM-DDTHH:MM:SS.ffffff+HH:MM[:SS[.ffffff]]
```
，如果
```
microsecond
```
 不为 0

-
```
YYYY-MM-DDTHH:MM:SS+HH:MM[:SS[.ffffff]]
```
，如果
```
microsecond
```
 为 0

 示例:

```
>>> import datetime as dt
>>> dt.datetime(2019, 5, 18, 15, 17, 8, 132263).isoformat()
'2019-05-18T15:17:08.132263'
>>> dt.datetime(2019, 5, 18, 15, 17, tzinfo=dt.timezone.utc).isoformat()
'2019-05-18T15:17:00+00:00'
```

 可选参数 sep (默认为
```
'T'
```
) 为单个分隔字符，会被放在结果的日期和时间两部分之间。 例如:

```
>>> import datetime as dt
>>> class TZ(dt.tzinfo):
...     """A time zone with an arbitrary, constant -06:39 offset."""
...     def utcoffset(self, when):
...         return dt.timedelta(hours=-6, minutes=-39)
...
>>> dt.datetime(2002, 12, 25, tzinfo=TZ()).isoformat(' ')
'2002-12-25 00:00:00-06:39'
>>> dt.datetime(2009, 11, 27, microsecond=100, tzinfo=TZ()).isoformat()
'2009-11-27T00:00:00.000100-06:39'
```

 可选参数 timespec 要包含的额外时间组件值 (默认为
```
'auto'
```
)。它可以是以下值之一：

-
```
'auto'
```
: 如果
```
microsecond
```
 为 0 则与
```
'seconds'
```
 相同，否则与
```
'microseconds'
```
 相同。

-
```
'hours'
```
: 以两个数码的
```
HH
```
 格式 包含
```
hour
```
。

-
```
'minutes'
```
: 以
```
HH:MM
```
 格式包含
```
hour
```
 和
```
minute
```
。

-
```
'seconds'
```
: 以
```
HH:MM:SS
```
 格式包含
```
hour
```
,
```
minute
```
 和
```
second
```
。

-
```
'milliseconds'
```
: 包含完整时间，但将秒值的小数部分截断至毫秒。 格式为
```
HH:MM:SS.sss
```
。

-
```
'microseconds'
```
: 以
```
HH:MM:SS.ffffff
```
 格式包含完整时间。

  备注
 排除掉的时间部分将被截断，而不是被舍入。

 对于无效的 timespec 参数将引发
```
ValueError
```
:

```
>>> import datetime as dt
>>> dt.datetime.now().isoformat(timespec='minutes')
'2002-12-25T00:00'
>>> my_datetime = dt.datetime(2015, 1, 1, 12, 30, 59, 0)
>>> my_datetime.isoformat(timespec='microseconds')
'2015-01-01T12:30:59.000000'
```

  在 3.6 版本发生变更: 增加了 timespec 形参。

   datetime.__str__()¶
 对于
```
datetime
```
 实例
```
d
```
，
```
str(d)
```
 等价于
```
d.isoformat(' ')
```
。

   datetime.ctime()¶
 返回一个表示日期和时间的字符串:

```
>>> import datetime as dt
>>> dt.datetime(2002, 12, 4, 20, 30, 40).ctime()
'Wed Dec  4 20:30:40 2002'
```

 输出字符串将 并不 包括时区信息，无论输入的是感知型还是简单型。

```
d.ctime()
```
 等效于:

```
time.ctime(time.mktime(d.timetuple()))
```

 在原生 C
```
ctime()
```
 函数遵循 C 标准的平台上 (
```
time.ctime()
```
 会发起对该函数的调用，但
```
datetime.ctime()
```
 并不会) 。

   datetime.strftime(format)¶
 返回一个由显式格式字符串所控制的，代表日期和时间的字符串。 另请参阅 strftime() 和 strptime() 的行为 和
```
datetime.isoformat()
```
。

   datetime.__format__(format)¶
 与
```
datetime.strftime()
```
 相同。 此方法使得在 格式化字符串字面值 中以及使用
```
str.format()
```
 时为
```
datetime
```
 对象指定格式字符串成为可能。 另请参阅 strftime() 和 strptime() 的行为 和
```
datetime.isoformat()
```
。

### 用法示例:
```
datetime
```
¶
 使用
```
datetime
```
 对象的例子：

```
>>> import datetime as dt

>>> # 使用 datetime.combine()
>>> d = dt.date(2005, 7, 14)
>>> t = dt.time(12, 30)
>>> dt.datetime.combine(d, t)
datetime.datetime(2005, 7, 14, 12, 30)

>>> # 使用 datetime.now()
>>> dt.datetime.now()
datetime.datetime(2007, 12, 6, 16, 29, 43, 79043)   # GMT +1
>>> dt.datetime.now(dt.timezone.utc)
datetime.datetime(2007, 12, 6, 15, 29, 43, 79060, tzinfo=datetime.timezone.utc)

>>> # 使用 datetime.strptime()
>>> my_datetime = dt.datetime.strptime("21/11/06 16:30", "%d/%m/%y %H:%M")
>>> my_datetime
datetime.datetime(2006, 11, 21, 16, 30)

>>> # 使用 datetime.timetuple() 获取由所有属性组成的元组
>>> tt = my_datetime.timetuple()
>>> for it in tt:
...     print(it)
...
2006    # 年
11      # 月
21      # 日
16      # 时
30      # 分
0       # 秒
1       # 周序号 (0 = 星期一)
325     # 自 1 月 1 日开始的天数
-1      # dst - 方法 tzinfo.dst() 返回 None

>>> # ISO 格式的日期
>>> ic = my_datetime.isocalendar()
>>> for it in ic:
...     print(it)
...
2006    # ISO 年
47      # ISO 第几周
2       # ISO 周序号

>>> # 格式化 datetime 对象
>>> my_datetime.strftime("%A, %d. %B %Y %I:%M%p")
'Tuesday, 21. November 2006 04:30PM'
>>> 'The {1} is {0:%d}, the {2} is {0:%B}, the {3} is {0:%I:%M%p}.'.format(my_datetime, "day", "month", "time")
'The day is 21, the month is November, the time is 04:30PM.'
```

 以下示例定义了一个
```
tzinfo
```
 子类，它捕获 Kabul, Afghanistan 时区的信息，该时区使用 +4 UTC 直到 1945 年，之后则使用 +4:30 UTC:

```
import datetime as dt

class KabulTz(dt.tzinfo):
    # 喀布尔曾使用 +4 直到 1945 年，后改为 +4:30
    UTC_MOVE_DATE = dt.datetime(1944, 12, 31, 20, tzinfo=dt.timezone.utc)

    def utcoffset(self, when):
        if when.year < 1945:
            return dt.timedelta(hours=4)
        elif (1945, 1, 1, 0, 0) <= when.timetuple()[:5] < (1945, 1, 1, 0, 30):
            # 带有歧义（“虚幻”）的半小时区间代表
            # 由于从 +4 改为 +4:30 导致的时间‘折叠’。
            # 如果 dt 落在此虚幻区间，则使用该折叠
            # 确定如何计算。 参见 PEP 495。
            return dt.timedelta(hours=4, minutes=(30 if when.fold else 0))
        else:
            return dt.timedelta(hours=4, minutes=30)

    def fromutc(self, when):
        # 遵循与在 datetime.tzinfo 中相同的验证
        if not isinstance(when, dt.datetime):
            raise TypeError("fromutc() requires a datetime argument")
        if when.tzinfo is not self:
            raise ValueError("when.tzinfo is not self")

        # 需要一个针对 fromutc 的自定义实现
        # 因为此函数的输入是 utc 日期时间值
        # 但其 tzinfo 设为 self。
        # 参见 datetime.astimezone 或 fromtimestamp。
        if when.replace(tzinfo=dt.timezone.utc) >= self.UTC_MOVE_DATE:
            return when + dt.timedelta(hours=4, minutes=30)
        else:
            return when + dt.timedelta(hours=4)

    def dst(self, when):
        # 喀布尔不实行夏令时。
        return dt.timedelta(0)

    def tzname(self, when):
        if when >= self.UTC_MOVE_DATE:
            return "+04:30"
        return "+04"
```

 上述
```
KabulTz
```
 的用法:

```
>>> tz1 = KabulTz()

>>> # 修改前日期时间
>>> dt1 = dt.datetime(1900, 11, 21, 16, 30, tzinfo=tz1)
>>> print(dt1.utcoffset())
4:00:00

>>> # 修改后日期时间
>>> dt2 = dt.datetime(2006, 6, 14, 13, 0, tzinfo=tz1)
>>> print(dt2.utcoffset())
4:30:00

>>> # 将日期时间转换至另一个时区
>>> dt3 = dt2.astimezone(dt.timezone.utc)
>>> dt3
datetime.datetime(2006, 6, 14, 8, 30, tzinfo=datetime.timezone.utc)
>>> dt2
datetime.datetime(2006, 6, 14, 13, 0, tzinfo=KabulTz())
>>> dt2 == dt3
True
```

##
```
time
```
 对象¶
 一个
```
time
```
 对象代表某日的（本地）时间，它独立于任何特定日期，并可通过
```
tzinfo
```
 对象来调整。
   class datetime.time(hour=0, minute=0, second=0, microsecond=0, tzinfo=None, *, fold=0)¶
 所有参数都是可选的。 tzinfo 可以是
```
None
```
，或者是一个
```
tzinfo
```
 子类的实例。 其余的参数必须是在下面范围内的整数：

-
```
0 <= hour < 24
```
,

-
```
0 <= minute < 60
```
,

-
```
0 <= second < 60
```
,

-
```
0 <= microsecond < 1000000
```
,

-
```
fold in [0, 1]
```
.

 如果给出一个此范围以外的参数，则会引发
```
ValueError
```
。 所有参数默认值均为 0 但 tzinfo 除外，其默认值为
```
None
```
。

 类属性：
   time.min¶
 最早的可表示
```
time
```
,
```
time(0, 0, 0, 0)
```
。

   time.max¶
 最晚的可表示
```
time
```
,
```
time(23, 59, 59, 999999)
```
。

   time.resolution¶
 两个不相等的
```
time
```
 对象之间可能的最小间隔，
```
timedelta(microseconds=1)
```
，但是请注意
```
time
```
 对象并不支持算术运算。

 实例属性（只读）：
   time.hour¶
 取值范围是
```
range(24)
```
。

   time.minute¶
 取值范围是
```
range(60)
```
。

   time.second¶
 取值范围是
```
range(60)
```
。

   time.microsecond¶
 取值范围是
```
range(1000000)
```
。

   time.tzinfo¶
 作为 tzinfo 参数被传给
```
time
```
 构造器的对象，如果没有传入值则为
```
None
```
。

   time.fold¶
 取值范围是
```
[0, 1]
```
。 用于在重复的时间段中消除边界时间的歧义。 （当夏令时结束时回拨时钟或由于政治原因导致当前时区的 UTC 时差减少就会出现重复时间段。） 取值 0 和 1 分别表示两个相同边界时间表示形式的前一个和后一个时间。
  Added in version 3.6.

```
time
```
 对象支持相等和顺序比较，当
```
a
```
 的时间在
```
b
```
 之前则认为
```
a
```
 小于
```
b
```
。
 简单型和感知型
```
time
```
 对象绝对不会相等。 简单型和感知型
```
time
```
 对象之间的顺序比较将会引发
```
TypeError
```
。
 如果两个操作数均为感知型，且具有相同的
```
tzinfo
```
 属性，则
```
tzinfo
```
 和
```
fold
```
 属性会被忽略并对基本时间值进行比较。 如果两个操作数均为感知型且具有不同的
```
tzinfo
```
 属性，则两个操作数将首先通过减去它们的 UTC 时差（从
```
self.utcoffset()
```
 获取）来进行调整。
  在 3.3 版本发生变更: 感知型和简单型
```
time
```
 实例之间的相等性比较不会引发
```
TypeError
```
。

 在布尔运算时，
```
time
```
 对象总是被视为真值。
  在 3.5 版本发生变更: 在 Python 3.5 之前，如果一个
```
time
```
 对象代表 UTC 午夜零时则会被视为假值。 此行为被认为容易引发困惑和错误，因此从 Python 3.5 起已被去除。 详情参见 bpo-13936 for more information。

 其他构造器：
   classmethod time.fromisoformat(time_string)¶
 返回一个对应于以任何有效的 ISO 8601 格式给出的 time_string 的
```
time
```
，下列格式除外:

1. 时区时差可能会有带小数的秒值。

1. 打头的
```
T
```
，通常在当日期和时间之间可能存在歧义时才有必要，不是必需的。

1. 带小数的秒值可以有任意多位数码（超过 6 位将被截断）。

1. 带小数的时和分是不受支持的。

 示例：

```
>>> import datetime as dt
>>> dt.time.fromisoformat('04:23:01')
datetime.time(4, 23, 1)
>>> dt.time.fromisoformat('T04:23:01')
datetime.time(4, 23, 1)
>>> dt.time.fromisoformat('T042301')
datetime.time(4, 23, 1)
>>> dt.time.fromisoformat('04:23:01.000384')
datetime.time(4, 23, 1, 384)
>>> dt.time.fromisoformat('04:23:01,000384')
datetime.time(4, 23, 1, 384)
>>> dt.time.fromisoformat('04:23:01+04:00')
datetime.time(4, 23, 1, tzinfo=datetime.timezone(datetime.timedelta(seconds=14400)))
>>> dt.time.fromisoformat('04:23:01Z')
datetime.time(4, 23, 1, tzinfo=datetime.timezone.utc)
>>> dt.time.fromisoformat('04:23:01+00:00')
datetime.time(4, 23, 1, tzinfo=datetime.timezone.utc)
```

  Added in version 3.7.

  在 3.11 版本发生变更: 在之前版本中，此方法仅支持可由
```
time.isoformat()
```
 发出的格式。

   classmethod time.strptime(date_string, format)¶
 返回一个对应于 date_string，根据 format 进行解析得到的
```
time
```
 对象。
 如果 format 不包含微秒或时区信息，这将等价于:

```
time(*(time.strptime(date_string, format)[3:6]))
```

 如果 date_string 和 format 无法被
```
time.strptime()
```
 解析或它返回一个不是时间元组的值则将引发
```
ValueError
```
。 另请参阅 strftime() 和 strptime() 的行为 和
```
time.fromisoformat()
```
。
  Added in version 3.14.

 实例方法：
   time.replace(hour=self.hour, minute=self.minute, second=self.second, microsecond=self.microsecond, tzinfo=self.tzinfo, *, fold=0)¶
 返回一个具有同样属性的新的
```
time
```
 ，但更新指定的形参。 请注意可以通过指定
```
tzinfo=None
```
 基于一个感知型
```
time
```
 创建一个简单型
```
time
```
，而不必转换时间数据。

```
time
```
 对象也被泛型函数
```
copy.replace()
```
 所支持。
  在 3.6 版本发生变更: 增加了 fold 形参。

   time.isoformat(timespec='auto')¶
 返回表示为下列 ISO 8601 格式之一的时间字符串：

-
```
HH:MM:SS.ffffff
```
，如果
```
microsecond
```
 不为 0

-
```
HH:MM:SS
```
，如果
```
microsecond
```
 为 0

-
```
HH:MM:SS.ffffff+HH:MM[:SS[.ffffff]]
```
，如果
```
utcoffset()
```
 不返回
```
None
```

-
```
HH:MM:SS+HH:MM[:SS[.ffffff]]
```
，如果
```
microsecond
```
 为 0 并且
```
utcoffset()
```
 不返回
```
None
```

 可选参数 timespec 要包含的额外时间组件值 (默认为
```
'auto'
```
)。它可以是以下值之一：

-
```
'auto'
```
: 如果
```
microsecond
```
 为 0 则与
```
'seconds'
```
 相同，否则与
```
'microseconds'
```
 相同。

-
```
'hours'
```
: 以两个数码的
```
HH
```
 格式 包含
```
hour
```
。

-
```
'minutes'
```
: 以
```
HH:MM
```
 格式包含
```
hour
```
 和
```
minute
```
。

-
```
'seconds'
```
: 以
```
HH:MM:SS
```
 格式包含
```
hour
```
,
```
minute
```
 和
```
second
```
。

-
```
'milliseconds'
```
: 包含完整时间，但将秒值的小数部分截断至毫秒。 格式为
```
HH:MM:SS.sss
```
。

-
```
'microseconds'
```
: 以
```
HH:MM:SS.ffffff
```
 格式包含完整时间。

  备注
 排除掉的时间部分将被截断，而不是被舍入。

 对于无效的 timespec 参数将引发
```
ValueError
```
。
 示例:

```
>>> import datetime as dt
>>> dt.time(hour=12, minute=34, second=56, microsecond=123456).isoformat(timespec='minutes')
'12:34'
>>> my_time = dt.time(hour=12, minute=34, second=56, microsecond=0)
>>> my_time.isoformat(timespec='microseconds')
'12:34:56.000000'
>>> my_time.isoformat(timespec='auto')
'12:34:56'
```

  在 3.6 版本发生变更: 增加了 timespec 形参。

   time.__str__()¶
 对于时间对象
```
t
```
，
```
str(t)
```
 等价于
```
t.isoformat()
```
。

   time.strftime(format)¶
 返回一个由显式格式字符串所控制的，代表时间的字符串。 另请参阅 strftime() 和 strptime() 的行为 和
```
time.isoformat()
```
。

   time.__format__(format)¶
 与
```
time.strftime()
```
 相同。 此方法使得在 格式化字符串字面值 中以及使用
```
str.format()
```
 时为
```
time
```
 对象指定格式字符串成为可能。 另请参阅 strftime() 和 strptime() 的行为 和
```
time.isoformat()
```
。

   time.utcoffset()¶
 如果
```
tzinfo
```
 为
```
None
```
，则返回
```
None
```
，否则返回
```
self.tzinfo.utcoffset(None)
```
，并且在后者不返回
```
None
```
 或一个幅度小于一天的
```
timedelta
```
 对象时将引发异常。
  在 3.7 版本发生变更: UTC 时差不再限制为一个整数分钟值。

   time.dst()¶
 如果
```
tzinfo
```
 为
```
None
```
，则返回
```
None
```
，否则返回
```
self.tzinfo.dst(None)
```
，并且在后者不返回
```
None
```
 或者一个幅度小于一天的
```
timedelta
```
 对象时将引发异常。
  在 3.7 版本发生变更: DST 差值不再限制为一个整数分钟值。

   time.tzname()¶
 如果
```
tzinfo
```
 为
```
None
```
，则返回
```
None
```
，否则返回
```
self.tzinfo.tzname(None)
```
，如果后者不返回
```
None
```
 或者一个字符串对象则将引发异常。

### 用法示例:
```
time
```
¶
 使用
```
time
```
 对象的例子:

```
>>> import datetime as dt
>>> class TZ1(dt.tzinfo):
...     def utcoffset(self, when):
...         return dt.timedelta(hours=1)
...     def dst(self, when):
...         return dt.timedelta(0)
...     def tzname(self, when):
...         return "+01:00"
...     def  __repr__(self):
...         return f"{self.__class__.__name__}()"
...
>>> t = dt.time(12, 10, 30, tzinfo=TZ1())
>>> t
datetime.time(12, 10, 30, tzinfo=TZ1())
>>> t.isoformat()
'12:10:30+01:00'
>>> t.dst()
datetime.timedelta(0)
>>> t.tzname()
'+01:00'
>>> t.strftime("%H:%M:%S %Z")
'12:10:30 +01:00'
>>> 'The {} is {:%H:%M}.'.format("time", t)
'The time is 12:10.'
```

##
```
tzinfo
```
 对象¶
   class datetime.tzinfo¶
 这是一个 abstract base class，也就是说该类不应被直接实例化。 请定义
```
tzinfo
```
 的子类来捕获有关特定时区的信息。to capture information about a particular time zone.

```
tzinfo
```
 的（某个实体子类）的实例可以被传给
```
datetime
```
 和
```
time
```
 对象的构造器。 这些对象会将它们的属性视为对应于本地时间，并且
```
tzinfo
```
 对象支持展示本地时间与 UTC 的差值、时区名称以及 DST 差值的方法，都是与传给它们的日期或时间对象的相对值。
 You need to derive a concrete subclass, and (at least) supply implementations of the standard
```
tzinfo
```
 methods needed by the
```
datetime
```
 methods you use. The
```
datetime
```
 module provides
```
timezone
```
, a simple concrete subclass of
```
tzinfo
```
 which can represent time zones with fixed offset from UTC such as UTC itself or North American EST and EDT.
 对于封存操作的特殊要求：一个
```
tzinfo
```
 子类必须具有可不带参数调用的
```
__init__()
```
 方法，否则它虽然可以被封存，但可能无法再次解封。 这是个技术性要求，在未来可能会被取消。
 一个
```
tzinfo
```
 的实体子类可能需要实现以下方法。 具体需要实现的方法取决于感知型
```
datetime
```
 对象如何使用它。 如果有疑问，可以简单地全部实现它们。

   tzinfo.utcoffset(dt)¶
 将本地时间与 UTC 时差返回为一个
```
timedelta
```
 对象，如果本地时区在 UTC 以东则为正值。 如果本地时区在 UTC 以西则为负值。
 这表示与 UTC 的 总计 时差；举例来说，如果一个
```
tzinfo
```
 对象同时代表时区和 DST 调整，则
```
utcoffset()
```
 应当返回两者的和。 如果 UTC 时差不确定则返回
```
None
```
。 在其他情况下返回值必须为一个
```
timedelta
```
 对象，其取值严格限制于
```
-timedelta(hours=24)
```
 和
```
timedelta(hours=24)
```
 之间（差值的幅度必须小于一天）。 大多数
```
utcoffset()
```
 的实现看起来可能像是以下两者之一:

```
return CONSTANT                 # 固定偏移类
return CONSTANT + self.dst(dt)  # 夏令时感知类
```

 如果
```
utcoffset()
```
 返回值不为
```
None
```
，则
```
dst()
```
 也不应返回
```
None
```
。
 默认的
```
utcoffset()
```
 实现会引发
```
NotImplementedError
```
。
  在 3.7 版本发生变更: UTC 时差不再限制为一个整数分钟值。

   tzinfo.dst(dt)¶
 将夏令时（DST）调整返回为一个
```
timedelta
```
 对象，如果 DST 信息未知则返回
```
None
```
。
 如果 DST 未启用则返回
```
timedelta(0)
```
。 如果 DST 已启用，则将差值作为一个
```
timedelta
```
 对象返回（请参阅
```
utcoffset()
```
 了解详情）。 请注意 DST 差值如果可用，就会直接被加入
```
utcoffset()
```
 所返回的 UTC 时差，因此无需额外查询
```
dst()
```
，除非你希望单独获取 DST 信息。 例如，
```
datetime.timetuple()
```
 会调用其
```
tzinfo
```
 属性的
```
dst()
```
 方法来确定应该如何设置
```
tm_isdst
```
 旗标，而
```
tzinfo.fromutc()
```
 会调用
```
dst()
```
 来在跨越时区时处理 DST 的改变。
 一个可以同时处理标准时和夏令时的
```
tzinfo
```
 子类的实例 tz 必须在此情形中保持一致：

```
tz.utcoffset(dt) - tz.dst(dt)
```
 must return the same result for every
```
datetime
```
 dt with
```
dt.tzinfo ==
tz
```
. For sane
```
tzinfo
```
 subclasses, this expression yields the time zone's "standard offset", which should not depend on the date or the time, but only on geographic location. The implementation of
```
datetime.astimezone()
```
 relies on this, but cannot detect violations; it's the programmer's responsibility to ensure it. If a
```
tzinfo
```
 subclass cannot guarantee this, it may be able to override the default implementation of
```
tzinfo.fromutc()
```
 to work correctly with
```
astimezone()
```
 regardless.
 大多数
```
dst()
```
 的实现可能会如以下两者之一:

```
import datetime as dt

def dst(self, when):
    # 固定偏移类：不考虑夏令时
    return dt.timedelta(0)
```

 或者:

```
import datetime as dt

def dst(self, when):
    # 此代码根据输入的 dt.year 设置时区的夏令时
    # 切换的开始和结束时刻 dston 和 dstoff，并以
    # 标准地方时表示。

    if dston <= when.replace(tzinfo=None) < dstoff:
        return dt.timedelta(hours=1)
    else:
        return dt.timedelta(0)
```

 默认的
```
dst()
```
 实现会引发
```
NotImplementedError
```
。
  在 3.7 版本发生变更: DST 差值不再限制为一个整数分钟值。

   tzinfo.tzname(dt)¶
 Return the time zone name corresponding to the
```
datetime
```
 object dt, as a string. Nothing about string names is defined by the
```
datetime
```
 module, and there's no requirement that it mean anything in particular. For example,
```
"GMT"
```
,
```
"UTC"
```
,
```
"-500"
```
,
```
"-5:00"
```
,
```
"EDT"
```
,
```
"US/Eastern"
```
,
```
"America/New York"
```
 are all valid replies. Return
```
None
```
 if a string name isn't known. Note that this is a method rather than a fixed string primarily because some
```
tzinfo
```
 subclasses will wish to return different names depending on the specific value of dt passed, especially if the
```
tzinfo
```
 class is accounting for daylight time.
 默认的
```
tzname()
```
 实现会引发
```
NotImplementedError
```
。

 These methods are called by a
```
datetime
```
 or
```
time
```
 object, in response to their methods of the same names. A
```
datetime
```
 object passes itself as the argument, and a
```
time
```
 object passes
```
None
```
 as the argument. A
```
tzinfo
```
 subclass's methods should therefore be prepared to accept a dt argument of
```
None
```
, or of class
```
datetime
```
.
 当传入
```
None
```
 时，应当由类的设计者来决定最佳回应方式。 例如，返回
```
None
```
 适用于希望该类提示时间对象不参与
```
tzinfo
```
 协议处理。 让
```
utcoffset(None)
```
 返回标准 UTC 时差也许会更有用处，因为并没有其他可用于发现标准时差的约定惯例。
 When a
```
datetime
```
 object is passed in response to a
```
datetime
```
 method,
```
dt.tzinfo
```
 is the same object as self.
```
tzinfo
```
 methods can rely on this, unless user code calls
```
tzinfo
```
 methods directly. The intent is that the
```
tzinfo
```
 methods interpret dt as being in local time, and not need worry about objects in other time zones.
 还有一个额外的
```
tzinfo
```
 方法，某个子类可能会希望重写它：
   tzinfo.fromutc(dt)¶
 此方法会由默认的
```
datetime.astimezone()
```
 实现来调用。 当被其调用时，
```
dt.tzinfo
```
 为 self，并且 dt 的日期和时间数据会被视为表示 UTC 时间。
```
fromutc()
```
 的目标是调整日期和时间数据，返回一个等价的表示 self 的本地时间的 datetime。
 大多数
```
tzinfo
```
 子类应该能够毫无问题地继承默认的
```
fromutc()
```
 实现。 它的健壮性足以处理固定差值的时区以及同时负责标准时和夏令时的时区，对于后者甚至还能处理 DST 转换时间在各个年份有变化的情况。 一个默认
```
fromutc()
```
 实现可能无法在所有情况下正确处理的例子是（与 UTC 的）标准时差取决于所经过的特定日期和时间，这种情况可能由于政治原因而出现。 默认的
```
astimezone()
```
 和
```
fromutc()
```
 实现可能无法生成你希望的结果，如果这个结果恰好是跨越了标准时差发生改变的时刻当中的某个小时值的话。
 忽略针对错误情况的代码，默认
```
fromutc()
```
 实现的行为方式如下:

```
import datetime as dt

def fromutc(self, when):
    # raise ValueError error if when.tzinfo is not self
    dtoff = when.utcoffset()
    dtdst = when.dst()
    # raise ValueError if dtoff is None or dtdst is None
    delta = dtoff - dtdst  # this is self's standard offset
    if delta:
        when += delta   # convert to standard local time
        dtdst = when.dst()
        # raise ValueError if dtdst is None
    if dtdst:
        return when + dtdst
    else:
        return when
```

 在以下
```
tzinfo_examples.py
```
 文件中有一些
```
tzinfo
```
 类的例子：

```
import datetime as dt

# A class capturing the platform's idea of local time.
# (May result in wrong values on historical times in
#  timezones where UTC offset and/or the DST rules had
#  changed in the past.)
import time

ZERO = dt.timedelta(0)
HOUR = dt.timedelta(hours=1)
SECOND = dt.timedelta(seconds=1)

STDOFFSET = dt.timedelta(seconds=-time.timezone)
if time.daylight:
    DSTOFFSET = dt.timedelta(seconds=-time.altzone)
else:
    DSTOFFSET = STDOFFSET

DSTDIFF = DSTOFFSET - STDOFFSET

class LocalTimezone(dt.tzinfo):

    def fromutc(self, when):
        assert when.tzinfo is self
        stamp = (when - dt.datetime(1970, 1, 1, tzinfo=self)) // SECOND
        args = time.localtime(stamp)[:6]
        dst_diff = DSTDIFF // SECOND
        # Detect fold
        fold = (args == time.localtime(stamp - dst_diff))
        return dt.datetime(*args, microsecond=when.microsecond,
                           tzinfo=self, fold=fold)

    def utcoffset(self, when):
        if self._isdst(when):
            return DSTOFFSET
        else:
            return STDOFFSET

    def dst(self, when):
        if self._isdst(when):
            return DSTDIFF
        else:
            return ZERO

    def tzname(self, when):
        return time.tzname[self._isdst(when)]

    def _isdst(self, when):
        tt = (when.year, when.month, when.day,
              when.hour, when.minute, when.second,
              when.weekday(), 0, 0)
        stamp = time.mktime(tt)
        tt = time.localtime(stamp)
        return tt.tm_isdst > 0

Local = LocalTimezone()

# A complete implementation of current DST rules for major US time zones.

def first_sunday_on_or_after(when):
    days_to_go = 6 - when.weekday()
    if days_to_go:
        when += dt.timedelta(days_to_go)
    return when

# US DST Rules
#
# This is a simplified (i.e., wrong for a few cases) set of rules for US
# DST start and end times. For a complete and up-to-date set of DST rules
# and timezone definitions, visit the Olson Database (or try pytz):
# http://www.twinsun.com/tz/tz-link.htm
# https://sourceforge.net/projects/pytz/ (might not be up-to-date)
#
# In the US, since 2007, DST starts at 2am (standard time) on the second
# Sunday in March, which is the first Sunday on or after Mar 8.
DSTSTART_2007 = dt.datetime(1, 3, 8, 2)
# and ends at 2am (DST time) on the first Sunday of Nov.
DSTEND_2007 = dt.datetime(1, 11, 1, 2)
# From 1987 to 2006, DST used to start at 2am (standard time) on the first
# Sunday in April and to end at 2am (DST time) on the last
# Sunday of October, which is the first Sunday on or after Oct 25.
DSTSTART_1987_2006 = dt.datetime(1, 4, 1, 2)
DSTEND_1987_2006 = dt.datetime(1, 10, 25, 2)
# From 1967 to 1986, DST used to start at 2am (standard time) on the last
# Sunday in April (the one on or after April 24) and to end at 2am (DST time)
# on the last Sunday of October, which is the first Sunday
# on or after Oct 25.
DSTSTART_1967_1986 = dt.datetime(1, 4, 24, 2)
DSTEND_1967_1986 = DSTEND_1987_2006

def us_dst_range(year):
    # Find start and end times for US DST. For years before 1967, return
    # start = end for no DST.
    if 2006 < year:
        dststart, dstend = DSTSTART_2007, DSTEND_2007
    elif 1986 < year < 2007:
        dststart, dstend = DSTSTART_1987_2006, DSTEND_1987_2006
    elif 1966 < year < 1987:
        dststart, dstend = DSTSTART_1967_1986, DSTEND_1967_1986
    else:
        return (dt.datetime(year, 1, 1), ) * 2

    start = first_sunday_on_or_after(dststart.replace(year=year))
    end = first_sunday_on_or_after(dstend.replace(year=year))
    return start, end

class USTimeZone(dt.tzinfo):

    def __init__(self, hours, reprname, stdname, dstname):
        self.stdoffset = dt.timedelta(hours=hours)
        self.reprname = reprname
        self.stdname = stdname
        self.dstname = dstname

    def __repr__(self):
        return self.reprname

    def tzname(self, when):
        if self.dst(when):
            return self.dstname
        else:
            return self.stdname

    def utcoffset(self, when):
        return self.stdoffset + self.dst(when)

    def dst(self, when):
        if when is None or when.tzinfo is None:
            # An exception may be sensible here, in one or both cases.
            # It depends on how you want to treat them.  The default
            # fromutc() implementation (called by the default astimezone()
            # implementation) passes a datetime with when.tzinfo is self.
            return ZERO
        assert when.tzinfo is self
        start, end = us_dst_range(when.year)
        # Can't compare naive to aware objects, so strip the timezone from
        # when first.
        when = when.replace(tzinfo=None)
        if start + HOUR <= when < end - HOUR:
            # DST is in effect.
            return HOUR
        if end - HOUR <= when < end:
            # Fold (an ambiguous hour): use when.fold to disambiguate.
            return ZERO if when.fold else HOUR
        if start <= when < start + HOUR:
            # Gap (a non-existent hour): reverse the fold rule.
            return HOUR if when.fold else ZERO
        # DST is off.
        return ZERO

    def fromutc(self, when):
        assert when.tzinfo is self
        start, end = us_dst_range(when.year)
        start = start.replace(tzinfo=self)
        end = end.replace(tzinfo=self)
        std_time = when + self.stdoffset
        dst_time = std_time + HOUR
        if end <= dst_time < end + HOUR:
            # Repeated hour
            return std_time.replace(fold=1)
        if std_time < start or dst_time >= end:
            # Standard time
            return std_time
        if start <= std_time < end - HOUR:
            # Daylight saving time
            return dst_time

Eastern  = USTimeZone(-5, "Eastern",  "EST", "EDT")
Central  = USTimeZone(-6, "Central",  "CST", "CDT")
Mountain = USTimeZone(-7, "Mountain", "MST", "MDT")
Pacific  = USTimeZone(-8, "Pacific",  "PST", "PDT")
```

 请注意同时负责标准时和夏令时的
```
tzinfo
```
 子类在每年两次的 DST 转换点上会出现不可避免的微妙问题。具体而言，考虑美国东部时区 (UTC -0500)，它的 EDT 从三月的第二个星期天 1:59 (EST) 之后一分钟开始，并在十一月的第一天星期天 1:59 (EDT) 之后一分钟结束:

```
  UTC   3:MM  4:MM  5:MM  6:MM  7:MM  8:MM
  EST  22:MM 23:MM  0:MM  1:MM  2:MM  3:MM
  EDT  23:MM  0:MM  1:MM  2:MM  3:MM  4:MM

start  22:MM 23:MM  0:MM  1:MM  3:MM  4:MM

  end  23:MM  0:MM  1:MM  1:MM  2:MM  3:MM
```

 当 DST 开始时（即 "start" 行），本地时钟从 1:59 跳到 3:00。 形式为 2:MM 的时间值在那一天是没有意义的，因此在 DST 开始那一天
```
astimezone(Eastern)
```
 不会输出包含
```
hour == 2
```
 的结果。 例如，在 2016 年春季时钟向前调整时，我们得到:

```
>>> import datetime as dt
>>> from tzinfo_examples import HOUR, Eastern
>>> u0 = dt.datetime(2016, 3, 13, 5, tzinfo=dt.timezone.utc)
>>> for i in range(4):
...     u = u0 + i*HOUR
...     t = u.astimezone(Eastern)
...     print(u.time(), 'UTC =', t.time(), t.tzname())
...
05:00:00 UTC = 00:00:00 EST
06:00:00 UTC = 01:00:00 EST
07:00:00 UTC = 03:00:00 EDT
08:00:00 UTC = 04:00:00 EDT
```

 当 DST 结束时（见 "end" 行），会有更糟糕的潜在问题：本地时间值中有一个小时是不可能没有歧义的：夏令时的最后一小时。 即以北美东部时间表示当天夏令时结束时的形式为 5:MM UTC 的时间。 本地时钟从 1:59（夏令时）再次跳回到 1:00（标准时）。 形式为 1:MM 的本地时间就是有歧义的。 此时
```
astimezone()
```
 是通过将两个相邻的 UTC 小时映射到两个相同的本地小时来模仿本地时钟的行为。 在这个北美东部时间的示例中，形式为 5:MM 和 6:MM 的 UTC 时间在转换为北美东部时间时都将被映射到 1:MM，但前一个时间会将
```
fold
```
 属性设为 0 而后一个时间会将其设为 1。 例如，在 2016 年秋季时钟往回调整时，我们得到:

```
>>> import datetime as dt
>>> from tzinfo_examples import HOUR, Eastern
>>> u0 = dt.datetime(2016, 11, 6, 4, tzinfo=dt.timezone.utc)
>>> for i in range(4):
...     u = u0 + i*HOUR
...     t = u.astimezone(Eastern)
...     print(u.time(), 'UTC =', t.time(), t.tzname(), t.fold)
...
04:00:00 UTC = 00:00:00 EDT 0
05:00:00 UTC = 01:00:00 EDT 0
06:00:00 UTC = 01:00:00 EST 1
07:00:00 UTC = 02:00:00 EST 0
```

 请注意不同的
```
datetime
```
 实例仅通过
```
fold
```
 属性值来加以区分，它们在比较时会被视为相等。
 Applications that can't bear wall-time ambiguities should explicitly check the value of the
```
fold
```
 attribute or avoid using hybrid
```
tzinfo
```
 subclasses; there are no ambiguities when using
```
timezone
```
, or any other fixed-offset
```
tzinfo
```
 subclass (such as a class representing only EST (fixed offset -5 hours), or only EDT (fixed offset -4 hours)).
  参见

```
zoneinfo
```
```
datetime
```
 模块有一个基本
```
timezone
```
 类（用来处理任意与 UTC 的固定时差）及其
```
timezone.utc
```
 属性（UTC
```
timezone
```
 实例）。

```
zoneinfo
```
 为 Python 带来了 IANA时区数据库 （也被称为 Olson 数据库），推荐使用它。

  IANA 时区数据库
该时区数据库 (通常称为 tz, tzdata 或 zoneinfo) 包含大量代码和数据用来表示全球许多有代表性的地点的本地时间的历史信息。 它会定期进行更新以反映各政治实体对时区边界、UTC 差值和夏令时规则的更改。

##
```
timezone
```
 对象¶

```
timezone
```
 类是
```
tzinfo
```
 的子类，它的每个实例都代表一个以与 UTC 的固定时差来定义的时区。
 此类的对象不可被用于代表某些特殊地点的时区信息，这些地点在一年的不同日期会使用不同的时差，或是在历史上对民用时间进行过调整。
   class datetime.timezone(offset, name=None)¶
 offset 参数必须指定为一个
```
timedelta
```
 对象，表示本地时间与 UTC 的时差。 它必须严格限制于
```
-timedelta(hours=24)
```
 和
```
timedelta(hours=24)
```
 之间，否则会引发
```
ValueError
```
。
 name 参数是可选的。 如果指定则必须为一个字符串，它将被用作
```
datetime.tzname()
```
 方法的返回值。
  Added in version 3.2.

  在 3.7 版本发生变更: UTC 时差不再限制为一个整数分钟值。

   timezone.utcoffset(dt)¶
 返回当
```
timezone
```
 实例被构造时指定的固定值。
 dt 参数会被忽略。 返回值是一个
```
timedelta
```
 实例，其值等于本地时间与 UTC 之间的时差。
  在 3.7 版本发生变更: UTC 时差不再限制为一个整数分钟值。

   timezone.tzname(dt)¶
 返回当
```
timezone
```
 实例被构造时指定的固定值。
 如果没有在构造器中提供 name，则
```
tzname(dt)
```
 所返回的名称将根据
```
offset
```
 值按以下规则生成。 如果 offset 为
```
timedelta(0)
```
，则名称为“UTC”，否则为字符串
```
UTC±HH:MM
```
，其中 ± 为
```
offset
```
 的正负符号，HH 和 MM 分别为表示
```
offset.hours
```
 和
```
offset.minutes
```
 的两个数码。
  在 3.6 版本发生变更: 由
```
offset=timedelta(0)
```
 生成的名称现在是简单的
```
'UTC'
```
，而不是
```
'UTC+00:00'
```
。

   timezone.dst(dt)¶
 总是返回
```
None
```
。

   timezone.fromutc(dt)¶
 返回
```
dt + offset
```
。 dt 参数必须为一个感知型
```
datetime
```
 实例，其中
```
tzinfo
```
 值设为
```
self
```
。

 类属性：
   timezone.utc¶
 UTC 时区，
```
timezone(timedelta(0))
```
。

##
```
strftime()
```
 和
```
strptime()
```
 的行为¶

```
date
```
,
```
datetime
```
 和
```
time
```
 对象都支持
```
strftime(format)
```
 方法，可用来创建由一个显式格式字符串所控制的表示时间的字符串。
 相反，
```
date.strptime()
```
、
```
datetime.strptime()
```
 和
```
time.strptime()
```
 类方法从表示时间的字符串和相应的格式字符串创建对象。
 下表提供了
```
strftime()
```
 与
```
strptime()
```
 的高层级比较：

```
strftime
```

```
strptime
```

 | 用法
  | 根据给定的格式将对象转换为字符串
  | 将字符串解析为给定相应格式的对象

 | 方法类型
  | 实例方法
  | 类方法

 | 签名
  |
```
strftime(format)
```
  |
```
strptime(date_string, format)
```

###
```
strftime()
```
 和
```
strptime()
```
 格式代码¶
 这些方法接受可被用于解析和格式化日期的格式代码:

```
>>> import datetime as dt
>>> dt.datetime.strptime('31/01/22 23:59:59.999999',
...                      '%d/%m/%y %H:%M:%S.%f')
datetime.datetime(2022, 1, 31, 23, 59, 59, 999999)
>>> _.strftime('%a %d %b %Y, %I:%M%p')
'Mon 31 Jan 2022, 11:59PM'
```

 The following is a list of all the format codes that the 1989 C standard requires, and these work on all platforms with a standard C implementation.

指示符
 含意
 示例
 备注

 |
```
%a
```
  | 当地工作日的缩写。
  |  Sun, Mon, ..., Sat (en_US);
 So, Mo, ..., Sa (de_DE)

   | (1)

 |
```
%A
```
  | 本地化的星期中每日的完整名称。
  |  Sunday, Monday, ..., Saturday (en_US);
 Sonntag, Montag, ..., Samstag (de_DE)

   | (1)

 |
```
%w
```
  | 以十进制数显示的工作日，其中0表示星期日，6表示星期六。
  | 0, 1, ..., 6
  |

 |
```
%d
```
  | 补零后，以十进制数显示的月份中的一天。
  | 01, 02, ..., 31
  | (9)

 |
```
%b
```
  | 当地月份的缩写。
  |  Jan, Feb, ..., Dec (en_US);
 Jan, Feb, ..., Dez (de_DE)

   | (1)

 |
```
%B
```
  | 本地化的月份全名。
  |  January, February, ..., December (en_US);
 Januar, Februar, ..., Dezember (de_DE)

   | (1)

 |
```
%m
```
  | 补零后，以十进制数显示的月份。
  | 01, 02, ..., 12
  | (9)

 |
```
%y
```
  | 补零后，以十进制数表示的，不带世纪的年份。
  | 00, 01, ..., 99
  | (9)

 |
```
%Y
```
  | 十进制数表示的带世纪的年份。
  | 0001, 0002, ..., 2013, 2014, ..., 9998, 9999
  | (2)

 |
```
%H
```
  | 以补零后的十进制数表示的小时（24 小时制）。
  | 00, 01, ..., 23
  | (9)

 |
```
%I
```
  | 以补零后的十进制数表示的小时（12 小时制）。
  | 01, 02, ..., 12
  | (9)

 |
```
%p
```
  | 本地化的 AM 或 PM 。
  |  AM, PM (en_US);
 am, pm (de_DE)

   | (1), (3)

 |
```
%M
```
  | 补零后，以十进制数显示的分钟。
  | 00, 01, ..., 59
  | (9)

 |
```
%S
```
  | 补零后，以十进制数显示的秒。
  | 00, 01, ..., 59
  | (4), (9)

 |
```
%f
```
  | 微秒作为一个十进制数，零填充到 6 位。
  | 000000, 000001, ..., 999999
  | (5)

 |
```
%z
```
  | UTC 偏移量，格式为
```
±HHMM[SS[.ffffff]]
```
 （如果是简单型对象则为空字符串）。
  | (空), +0000, -0400, +1030, +063415, -030712.345216
  | (6)

 |
```
%Z
```
  | 时区名称（如果对象为简单型则为空字符串）。
  | (空), UTC, GMT
  | (6)

 |
```
%j
```
  | 以补零后的十进制数表示的一年中的日序号。
  | 001, 002, ..., 366
  | (9)

 |
```
%U
```
  | 以补零后的十进制数表示的一年中的周序号（星期日作为每周的第一天）。 在新的一年中第一个星期日之前的所有日子都被视为是在第 0 周。
  | 00, 01, ..., 53
  | (7), (9)

 |
```
%W
```
  | 以补零后的十进制数表示的一年中的周序号（星期一作为每周的第一天）。 在新的一年中第一个星期一之前的所有日子都被视为是在第 0 周。
  | 00, 01, ..., 53
  | (7), (9)

 |
```
%c
```
  | 本地化的适当日期和时间表示。
  |  Tue Aug 16 21:30:00 1988 (en_US);
 Di 16 Aug 21:30:00 1988 (de_DE)

   | (1)

 |
```
%x
```
  | 本地化的适当日期表示。
  |  08/16/88 (None);
 08/16/1988 (en_US);
 16.08.1988 (de_DE)

   | (1)

 |
```
%X
```
  | 本地化的适当时间表示。
  |  21:30:00 (en_US);
 21:30:00 (de_DE)

   | (1)

 |
```
%%
```
  | 字面的
```
'%'
```
 字符。
  | %
  |
   Several additional directives not required by the C89 standard are included for convenience. These parameters all correspond to ISO 8601 date values.

指示符
 含意
 示例
 备注

 |
```
%G
```
  | 带有世纪的 ISO 8601 年份，表示包含大部分 ISO 星期 (
```
%V
```
) 的年份。
  | 0001, 0002, ..., 2013, 2014, ..., 9998, 9999
  | (8)

 |
```
%u
```
  | 以十进制数显示的 ISO 8601 星期中的日序号，其中 1 表示星期一。
  | 1, 2, ..., 7
  |

 |
```
%V
```
  | 以十进制数显示的 ISO 8601 星期，以星期一作为每周的第一天。 第 01 周为包含 1 月 4 日的星期。
  | 01, 02, ..., 53
  | (8), (9)

 |
```
%:z
```
  |
```
±HH:MM[:SS[.ffffff]]
```
 形式的 UTC 偏移量（如果是简单型对象则为空字符串）。
  | (空), +00:00, -04:00, +10:30, +06:34:15, -03:07:12.345216
  | (6)

   These may not be available on all platforms when used with the
```
strftime()
```
 method. The ISO 8601 year and ISO 8601 week directives are not interchangeable with the year and week number directives above. Calling
```
strptime()
```
 with incomplete or ambiguous ISO 8601 directives will raise a
```
ValueError
```
.
 对完整格式代码集的支持在不同平台上有所差异，因为 Python 要调用所在平台的 C 库的
```
strftime()
```
 函数，而不同平台的差异是很常见的。 要查看你所用平台所支持的完整格式代码集，请参阅 strftime(3) 文档。 不同的平台在处理不支持的格式说明符方面也有差异。
  Added in version 3.6: 增加了
```
%G
```
,
```
%u
```
 和
```
%V
```
。

  Added in version 3.12:
```
%:z
```
 was added.

### 技术细节¶
 总体而言，
```
d.strftime(fmt)
```
 类似于
```
time
```
 模块的
```
time.strftime(fmt, d.timetuple())
```
 但是并非所有对象都支持
```
timetuple()
```
 方法。
 对于
```
datetime.strptime()
```
 和
```
date.strptime()
```
 类方法，默认值为
```
1900-01-01T00:00:00.000
```
: 任何未在格式字符串中指明的部分都将从默认值中提取。
  备注
 没有分隔符的格式字符串解析时可能会有歧义。 例如，对于
```
%Y%m%d
```
，字符串
```
2026111
```
 可以被解析为
```
2026-11-01
```
 或
```
2026-01-11
```
。 请使用分隔符来确保输入的解析符合意图。

  备注
 当被用于解析缺少年份的日期时，
```
datetime.strptime()
```
 和
```
date.strptime()
```
 会在遇到 2 月 29 日时引发异常因为默认年份 1900 不是 闰年。 请总是在解析之前向不完整的日期字符串添加一个默认的闰年。

```
>>> import datetime as dt
>>> value = "2/29"
>>> dt.datetime.strptime(value, "%m/%d")
Traceback (most recent call last):
...
ValueError: day 29 must be in range 1..28 for month 2 in year 1900
>>> dt.datetime.strptime(f"1904 {value}", "%Y %m/%d")
datetime.datetime(1904, 2, 29, 0, 0)
```

 使用
```
datetime.strptime(date_string, format)
```
 等价于:

```
datetime(*(time.strptime(date_string, format)[0:6]))
```

 除非格式中包含秒以下的部分或时区差值信息，它们在
```
datetime.strptime
```
 中受支持但会被
```
time.strptime
```
 所丢弃。
 对于
```
time
```
 对象，年、月、日的格式代码不应被使用，因为
```
time
```
 对象没有这些值。 如果它们仍被使用，则年份将被替换为 1900 而月和日将被替换为 1。
 对于
```
date
```
 对象，时、分、秒和微秒的格式代码不应被使用，因为
```
date
```
 对象没有这些值。 如果它们仍被使用，则都将被替换为 0。
 出于相同的原因，对于包含当前区域设置字符集所无法表示的 Unicode 码位的格式字符串的处理方式也取决于具体平台。 在某些平台上这样的码位会不加修改地原样输出，而在其他平台上
```
strftime
```
 则可能引发
```
UnicodeError
```
 或只返回一个空字符串。
 注释：

1. 因为该格式依赖于当前语言区域，所以在假定输出值时应当仔细考虑。 字段顺序可能会有变化（例如 "month/day/year" 和 "day/month/year"），并且输出还可能包含非 ASCII 字符。

1.
```
strptime()
```
 方法能够解析整个 [1, 9999] 范围内的年份，但 < 1000 的年份必须加零填充为 4 位数字宽度。
  在 3.2 版本发生变更: 在之前的版本中，
```
strftime()
```
 方法只限用于 >= 1900 的年份。

  在 3.3 版本发生变更: 在 3.2 版中，
```
strftime()
```
 方法只限用于 >= 1000 的年份。

1. 当与
```
strptime()
```
 方法一起使用时，如果使用
```
%I
```
 指示符来解析时，则
```
%p
```
 指示符只会影响输出时字段。

1. 与
```
time
```
 模块不同的是，
```
datetime
```
 模块不支持闰秒。

1. 当与
```
strptime()
```
 方法一起使用时，
```
%f
```
 指示符可接受一至六个数码及左边的零填充。
```
%f
```
 是对 C 标准中格式字符集的扩展（但单独在 datetime 对象中实现，因此它总是可用）。

1. 对于简单型对象，
```
%z
```
,
```
%:z
```
 和
```
%Z
```
 格式代码会被替换为空字符串。
 对于一个感知型对象而言：

```
%z
```
```
utcoffset()
```
 会被转换为
```
±HHMM[SS[.ffffff]]
```
 形式的字符串，其中
```
HH
```
 为给出 UTC 时差的小时部分的 2 位数码字符串，
```
MM
```
 为给出 UTC 时差的分钟部分的 2 位数码字符串，
```
SS
```
 为给出 UTC 时差的秒部分的 2 位数码字符串，而
```
ffffff
```
 则为给出 UTC 时差的微秒部分的 6 位数码字符串。 当时差为整数秒时
```
ffffff
```
 部分将被省略，而当时差为整数分钟时
```
ffffff
```
 和
```
SS
```
 部分都将被省略。 举例来说，如果
```
utcoffset()
```
 返回
```
timedelta(hours=-3, minutes=-30)
```
，则
```
%z
```
 会被替换为字符串
```
'-0330'
```
。

   在 3.7 版本发生变更: UTC 时差不再限制为一个整数分钟值。

  在 3.7 版本发生变更: When the
```
%z
```
 directive is provided to the
```
strptime()
```
 method, the UTC offsets can have a colon as a separator between hours, minutes and seconds. For example,
```
'+01:00:00'
```
 will be parsed as an offset of one hour. In addition, providing
```
'Z'
```
 is identical to
```
'+00:00'
```
.

```
%:z
```
Behaves exactly as
```
%z
```
, but has a colon separator added between hours, minutes and seconds.

```
%Z
```
在
```
strftime()
```
 中，如果
```
tzname()
```
 返回
```
None
```
 则
```
%Z
```
 会被替换为一个空字符串；在其他情况下
```
%Z
```
 会被替换为该返回值，它必须为一个字符串。

```
strptime()
```
 仅接受特定的
```
%Z
```
 值：

1. 你的机器的区域设置可以是
```
time.tzname
```
 中的任何值

1. 硬编码的值
```
UTC
```
 和
```
GMT
```

 这样生活在日本的人可用的值为
```
JST
```
,
```
UTC
```
 和
```
GMT
```
，但可能没有
```
EST
```
。 它将引发
```
ValueError
```
 表示无效的值。

   在 3.2 版本发生变更: 当提供
```
%z
```
 指示符给
```
strptime()
```
 方法时，将产生一个感知型
```
datetime
```
 对象。 结果的
```
tzinfo
```
 将被设为一个
```
timezone
```
 实例。

1. 当与
```
strptime()
```
 方法一起使用时，
```
%U
```
 和
```
%W
```
 仅用于指定了星期值和日历年份 (
```
%Y
```
) 的计算。

1. 类似于
```
%U
```
 和
```
%W
```
，
```
%V
```
 仅用于在
```
strptime()
```
 格式字符串中指定了星期值和 ISO 年份 (
```
%G
```
) 的计算。 还要注意
```
%G
```
 和
```
%Y
```
 是不可互换的。

1. 当与
```
strptime()
```
 方法一起使用时，前导的零在格式
```
%d
```
,
```
%m
```
,
```
%H
```
,
```
%I
```
,
```
%M
```
,
```
%S
```
,
```
%j
```
,
```
%U
```
,
```
%W
```
 和
```
%V
```
 中是可选的。 格式
```
%y
```
 则要求有前导的零。

1. 当使用
```
strptime()
```
 解析月份和日期时，始终在格式中包括年份。 如果你需要解析的值缺少年份，则添加一个显式的占位闰年。 否则当你的代码遇到一个闰日时将引发异常因为解析器所使用的默认年份 (1900) 不是闰年。 用户会在每个闰年碰到这个程序错误。

```
>>> month_day = "02/29"
>>> dt.datetime.strptime(f"{month_day};1984", "%m/%d;%Y")  # No leap year bug.
datetime.datetime(1984, 2, 29, 0, 0)
```

  从 3.13 版起已弃用，将在 3.15 版中移除:
```
strptime()
```
 calls using a format string containing a day of month without a year now emit a
```
DeprecationWarning
```
. In 3.15 or later we may change this into an error or change the default year to a leap year. See gh-70647.

 备注
   [1] If, that is, we ignore the effects of relativity.
   [2] 这与 Dershowitz 和 Reingold 所著 Calendrical Calculations 中“预期格列高利”历法的定义一致，它是适用于该书中所有运算的基础历法。 请参阅该书了解在预期格利高利历序列与许多其他历法系统之间进行转换的算法。
   [3] 请参阅 R. H. van Gent 所著 ISO 8601 历法的数学指南 以获取更完整的说明。

### 目录

-
```
datetime
```
 --- 基本日期和时间类型
- 感知型对象和简单型对象

- 常量

- 可用的类型
- 通用特征属性

- 确定一个对象是感知型还是简单型

-
```
timedelta
```
 对象
- 用法示例:
```
timedelta
```

-
```
date
```
 对象
- 用法示例:
```
date
```

-
```
datetime
```
 对象
- 用法示例:
```
datetime
```

-
```
time
```
 对象
- 用法示例:
```
time
```

-
```
tzinfo
```
 对象

-
```
timezone
```
 对象

-
```
strftime()
```
 和
```
strptime()
```
 的行为
-
```
strftime()
```
 和
```
strptime()
```
 格式代码

- 技术细节

#### 上一主题
 数据类型

#### 下一主题

```
zoneinfo
```
 --- IANA 时区支持

### 当前页

- 报告代码错误

- 改进本页面

-  显示源码

-  显示翻译源

  «

### 导航

-  索引

-  模块 |

-  下一页 |

-  上一页 |

-

- Python »

-

-

-  3.14.6 Documentation »

- Python 标准库 »

- 数据类型 »

-
```
datetime
```
 --- 基本日期和时间类型

-
 |

-   主题  自动 明亮 黑暗   |

  © 版权 2001 Python Software Foundation.  本页面采用 Python 软件基金会许可证第 2 版授权。  文档中的示例、代码片段及其他代码内容额外采用零条款 BSD 许可证授权。  更多信息请参阅《 历史与许可 》。  Python 软件基金会是一家非营利性公司。 请进行捐赠。   最后更新于8月 05, 2026 (11:17 UTC) 。 发现了错误？  使用Sphinx 8.2.3 创建。
