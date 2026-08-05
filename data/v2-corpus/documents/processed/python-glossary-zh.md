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

- 术语对照表

-
 |

-   主题  自动 明亮 黑暗   |

# 术语对照表¶

```
>>>
```
¶
interactive shell 中默认的 Python 提示符。往往会显示于能以交互方式在解释器里执行的样例代码之前。

```
...
```
¶
具有以下含义：

- interactive shell 中输入特殊代码时默认的 Python 提示符，特殊代码包括缩进的代码块，左右成对分隔符（圆括号、方括号、花括号或三重引号等）之内，或是在指定一个装饰器之后。

- 三点形式的 省略符 对象。

 abstract base class -- 抽象基类¶
抽象基类简称 ABC，是对 duck-typing 的补充，它提供了一种定义接口的新方式，相比之下其他技巧例如
```
hasattr()
```
 显得过于笨拙或有微妙错误 (例如使用 魔术方法)。 ABC 引入了虚拟子类，这种类并非继承自其他类，但却仍能被
```
isinstance()
```
 和
```
issubclass()
```
 所认可；详见
```
abc
```
 模块文档。Python 自带许多内置的 ABC 用于实现数据结构（在
```
collections.abc
```
 模块中）、数字（在
```
numbers
```
 模块中）、流（在
```
io
```
 模块中）、导入查找器和加载器（在
```
importlib.abc
```
 模块中）。你可以使用
```
abc
```
 模块来创建自己的 ABC。

 annotate function -- 标注函数¶
A callable that can be called to retrieve the annotations of an object. Annotate functions are usually functions, automatically generated as the
```
__annotate__
```
 attribute of functions, classes, and modules. Annotate functions are a subset of evaluate functions.

 annotation -- 标注¶
关联到某个变量、类属性、函数形参或返回值的标签，被约定作为 类型注解 来使用。
 局部变量的标注在运行时不可被访问，但全局变量、类属性和函数的标注可分别通过在模块、类和函数上调用
```
annotationlib.get_annotations()
```
 来提取。
 参见 variable annotation, function annotation, PEP 484, PEP 526 和 PEP 649，其中对此功能进行了描述。另请参见 注解最佳实践 了解使用标注的最佳实践。

 argument -- 参数¶
在调用函数时传给 function (或 method) 的值。参数分为两种：

- 关键字参数: 在函数调用中前面带有标识符 (例如
```
name=
```
) 或者作为包含在前面带有
```
**
```
 的字典里的值传入。举例来说，
```
3
```
 和
```
5
```
 在以下对
```
complex()
```
 的调用中均属于关键字参数:

```
complex(real=3, imag=5)
complex(**{'real': 3, 'imag': 5})
```

- 位置参数: 不属于关键字参数的参数。位置参数可出现于参数列表的开头以及/或者作为前面带有
```
*
```
 的 iterable 里的元素被传入。举例来说，
```
3
```
 和
```
5
```
 在以下调用中均属于位置参数:

```
complex(3, 5)
complex(*(3, 5))
```

 参数会被赋值给函数体中对应的局部变量。有关赋值规则参见 调用 一节。根据语法，任何表达式都可用来表示一个参数；最终算出的值会被赋给对应的局部变量。
 另参见 parameter 术语表条目，常见问题中 参数与形参的区别 以及 PEP 362。

 asynchronous context manager -- 异步上下文管理器¶
此种对象通过定义
```
__aenter__()
```
 和
```
__aexit__()
```
 方法来对
```
async with
```
 语句中的环境进行控制。由 PEP 492 引入。

 asynchronous generator -- 异步生成器¶
Informally used to mean either an asynchronous generator function or an asynchronous generator iterator, depending on context. The formal terms asynchronous generator function and asynchronous generator iterator are uncommon in practice; "asynchronous generator" alone is almost always sufficient.

 asynchronous generator function¶
A function which returns an asynchronous generator iterator. It looks like a coroutine function defined with
```
async def
```
 except that it contains
```
yield
```
 expressions for producing a series of values usable in an
```
async for
```
 loop. See PEP 525.
 一个异步生成器函数可能包含
```
await
```
 表达式或者
```
async for
```
 以及
```
async with
```
 语句。

 asynchronous generator iterator -- 异步生成器迭代器¶
An object created by an asynchronous generator function.
 此对象属于 asynchronous iterator，当使用
```
__anext__()
```
 方法调用时会返回一个可等待对象来执行异步生成器函数的函数体直到下一个
```
yield
```
 表达式。
 每个
```
yield
```
 会临时暂停处理过程，记住执行状态（包括局部变量和挂起的 try 语句）。当 异步生成器迭代器 通过
```
__anext__()
```
 所返回的另一个可等待对象有效地恢复时，它会从离开位置恢复处理过程。参见 PEP 492 和 PEP 525.

 asynchronous iterable -- 异步可迭代对象¶
一个可以在
```
async for
```
 语句中使用的对象。必须通过它的
```
__aiter__()
```
 方法返回一个 asynchronous iterator。由 PEP 492 引入。

 asynchronous iterator -- 异步迭代器¶
一个实现了
```
__aiter__()
```
 和
```
__anext__()
```
 方法的对象。
```
__anext__()
```
 必须返回一个 awaitable 对象。
```
async for
```
 会处理异步迭代器的
```
__anext__()
```
 方法所返回的可等待对象直到其引发一个
```
StopAsyncIteration
```
 异常。由 PEP 492 引入。

 atomic operation -- 原子化操作¶
作为一个单独的、不可再分的步骤执行的操作；没有其他线程能看到其完成一半的状态，其结果将在全部完成时可见。Python 不保证高层级语句是原子化的（例如，
```
x += 1
```
 将执行多个字节码操作因而不是原子化的）。原子化性质仅在显式写入文档时被保证。另请参阅 race condition 和 data race。

 attached thread state -- 附加线程状态¶
为当前 OS 线程激活的 thread state。
 当附加 thread state 时，OS 线程将可访问完整 Python C API 并能安全地唤起字节码解释器。
 除非函数明确指出，否则尝试在没有附加线程状态的情况下调用 C API 将导致致命错误或未定义行为。线程状态可以由用户通过 C API 显式地附加和分离，也可以由运行时隐式地附加和分离，包括在阻塞 C 调用期间和调用之间的字节码解释器。
 在大多数 Python 构建版中，具有附加线程状态意味着调用方持有当前解释器的 GIL，因此在给定时刻只有一个 OS 线程可以具有附加线程状态。在 Python 的 自由线程构建版 中，线程可以并发地持有附加线程状态，从而允许字节码解释器的真正并行性。

 attribute -- 属性¶
关联到一个对象的值，通常使用点号表达式按名称来引用。举例来说，如果对象 o 具有属性 a 则可以用 o.a 来引用它。
 如果对象允许，将未被定义为 名称（标识符和关键字） 的非标识名称用作一个对象的属性也是可以的，例如使用
```
setattr()
```
。 这样的属性将无法使用点号表达式来访问，而是必须通过
```
getattr()
```
 来获取。

 awaitable -- 可等待对象¶
一个可在
```
await
```
 表达式中使用的对象。可以是 coroutine 或是具有
```
__await__()
```
 方法的对象。参见 PEP 492。

 BDFL¶
“终身仁慈独裁者”的英文缩写，即 Guido van Rossum，Python 的创造者。

 binary file -- 二进制文件¶
file object 能够读写 字节型对象。二进制文件的例子包括以二进制模式 (
```
'rb'
```
,
```
'wb'
```
 或
```
'rb+'
```
) 打开的文件、
```
sys.stdin.buffer
```
、
```
sys.stdout.buffer
```
 以及
```
io.BytesIO
```
 和
```
gzip.GzipFile
```
 的实例。
 另请参见 text file 了解能够读写
```
str
```
 对象的文件对象。

 borrowed reference -- 借入引用¶
在 Python 的 C API 中，借用引用是指一种对象引用，使用该对象的代码并不持有该引用。如果对象被销毁则它就会变成一个悬空指针。 例如，垃圾回收器可以移除对象的最后一个 strong reference 来销毁它。
 推荐在 borrowed reference 上调用
```
Py_INCREF()
```
 以将其原地转换为 strong reference，除非是当该对象无法在借入引用的最后一次使用之前被销毁。
```
Py_NewRef()
```
 函数可以被用来创建一个新的 strong reference。

 bytes-like object -- 字节型对象¶
支持 缓冲协议 并且能导出 C-contiguous 缓冲的对象。这包括所有
```
bytes
```
、
```
bytearray
```
 和
```
array.array
```
 对象，以及许多普通
```
memoryview
```
 对象。字节型对象可在多种二进制数据操作中使用；这些操作包括压缩、保存为二进制文件以及通过套接字发送等。
 某些操作需要可变的二进制数据。这种对象在文档中常被称为“可读写字节类对象”。可变缓冲对象的例子包括
```
bytearray
```
 以及
```
bytearray
```
 的
```
memoryview
```
。其他操作要求二进制数据存放于不可变对象 ("只读字节类对象")；这种对象的例子包括
```
bytes
```
 以及
```
bytes
```
 对象的
```
memoryview
```
。

 bytecode -- 字节码¶
Python 源代码会被编译为字节码，即 CPython 解释器中表示 Python 程序的内部代码。字节码还会缓存在
```
.pyc
```
 文件中，这样第二次执行同一文件时速度更快（可以免去将源码重新编译为字节码）。这种 "中间语言" 运行在根据字节码执行相应机器码的 virtual machine 之上。请注意不同 Python 虚拟机上的字节码不一定通用，也不一定能在不同 Python 版本上兼容。
 字节码指令列表可以在 dis 模块 的文档中查看。

 callable -- 可调用对象¶
可调用对象就是可以执行调用运算的对象，并可能附带一组参数 (参见 argument)，使用以下语法:

```
callable(argument1, argument2, argumentN)
```

 function，还可扩展到 method 等，就属于可调用对象。实现了
```
__call__()
```
 方法的类的实例也属于可调用对象。

 callback -- 回调¶
一个作为参数被传入以用以在未来的某个时刻被调用的子例程函数。

 class -- 类¶
用来创建用户定义对象的模板。类定义通常包含对该类的实例进行操作的方法定义。

 class variable -- 类变量¶
在类中定义的变量，并且仅限在类的层级上修改 (而不是在类的实例中修改)。

 closure variable -- 闭包变量¶
引用自 nested scope 的 free variable，它是在外层作用域中定义而不是在运行时自全局或内置命名空间中取得。可能使用
```
nonlocal
```
 关键字显式地定义以允许写入访问，或者如果变量仅供读取则只需隐式地定义。
 例如，在以下代码的
```
inner
```
 函数中，
```
x
```
 和
```
print
```
 均为 自由变量，但只有
```
x
```
 属于 闭包变量:

```
def outer():
    x = 0
    def inner():
        nonlocal x
        x += 1
        print(x)
    return inner
```

 由于
```
codeobject.co_freevars
```
 属性的存在（虽然名称如此，但其仅包括闭包变量名称而非列出所有被引用的自由变量），更一般化的术语 free variable 有时在即便本意是专指闭包变量时也会被使用。

 complex number -- 复数¶
对普通实数系统的扩展，其中所有数字都被表示为一个实部和一个虚部的和。虚数是虚数单位 (
```
-1
```
 的平方根) 的实倍数，通常在数学中写为
```
i
```
，在工程学中写为
```
j
```
。Python 内置了对复数的支持，采用工程学标记方式；虚部带有一个
```
j
```
 后缀，例如
```
3+1j
```
。如果需要
```
math
```
 模块内对象的对应复数版本，请使用
```
cmath
```
，复数的使用是一个比较高级的数学特性。如果你感觉没有必要，忽略它们也几乎不会有任何问题。

 concurrency -- 并发¶
一个计算机程序同时执行多个任务的能力。Python 提供了用于编写采用不同并发形式的程序的多个库。
```
asyncio
```
 是用于处理异步任务和协程的库。
```
threading
```
 提供对操作系统线程的访问而
```
multiprocessing
```
 提供对操作系统进程的访问。多核心处理器可以同时在不同的 CPU 核心上执行线程和进程 (参见 parallelism)。

 concurrent modification -- 并发修改¶
当多个线程同时修改共享数据时。没有适当同步的并发修改可能导致 竞争条件，还可能触发 数据竞争，数据损坏，或是两者兼有。

 context -- 上下文¶
此术语根据其所在场合和使用方式的不同而具有不同的含义。一些常见的含义为：

- 通过
```
with
```
 语句由一个 context manager 所创建的临时环境或状态。

- 一组关联到特定
```
contextvars.Context
```
 对象并通过
```
ContextVar
```
 对象来访问的键值绑定。另请参见 context variable。

- 一个
```
contextvars.Context
```
 对象。另请参见 current context。

 context management protocol -- 上下文管理协议¶
```
__enter__()
```
 和
```
__exit__()
```
 方法将由
```
with
```
 语句来调用。参见 PEP 343。

 context manager -- 上下文管理器¶
一个实现了 context management protocol 并负责控制某个
```
with
```
 语句内的环境的对象。 参见 PEP 343。

 context variable -- 上下文变量¶
一个具体值取决于哪个上下文是 current context 的变量。这些值是通过
```
contextvars.ContextVar
```
 对象来访问的。上下文变量主要被用来隔离并发的异步任务之间的状态。

 contiguous -- 连续¶
一个缓冲如果是 C 连续 或 Fortran 连续 就会被认为是连续的。零维缓冲是 C 和 Fortran 连续的。在一维数组中，所有条目必须在内存中彼此相邻地排列，采用从零开始的递增索引顺序。在多维 C-连续数组中，当按内存地址排列时用最后一个索引访问条目时速度最快。但是在 Fortran 连续数组中则是用第一个索引最快。

 coroutine -- 协程¶
协程是子例程的更一般形式。子例程可以在某一点进入并在另一点退出。协程则可以在许多不同的点上进入、退出和恢复。它们可通过
```
async def
```
 语句来实现。参见 PEP 492。

 coroutine function -- 协程函数¶
返回一个 coroutine 对象的函数。协程函数可通过
```
async def
```
 语句来定义，并可能包含
```
await
```
、
```
async for
```
 和
```
async with
```
 关键字。这些特性是由 PEP 492 引入的。

 CPython¶
Python 编程语言的规范实现，在 python.org 上发布。"CPython" 一词用于在必要时将此实现与其他实现例如 Jython 或 IronPython 相区别。

 current context -- 当前上下文¶
在当前被
```
ContextVar
```
 对象用来访问 (获取或设置) 上下文变量 的值的 context (
```
contextvars.Context
```
 对象)。 每个线程都具有它自己的当前上下文。用于执行异步任务 (参见
```
asyncio
```
) 的框架会在每个任务开始或恢复执行时将任务关联到一个成为当前上下文的上下文。

 cyclic isolate -- 循环隔离¶
某个引用循环中的子分组，其中包含的一个或多个对象会相互引用但不会被分组以外的对象所引用。 循环垃圾回收器 的目标是标识出这些分组并打断其引用循环以便回收相应的内存。

 data race -- 数据竞争¶
多个线程并发地访问相同内存位置的情况，至少有一个访问是写入，并且各线程没有使用任何同步机制来控制它们的访问。数据竞争会导致 non-deterministic 行为并可造成数据损坏。正确使用 锁 和其他 同步原语 可以防止数据竞争。请注意数据竞争只会发生在原生代码中，但是 native code 可能会在 Python API 中暴露出来。另请参阅 race condition 和 thread-safe.

 deadlock -- 死锁¶
在某种情况下有两个以上任务（线程、进程或协程）无限地等待彼此释放资源或完成动作，导致任何一个都无法继续执行。举例来说，如果线程 A 持有锁 1 并等待锁 2，而线程 B 持有锁 2 并等待锁 1，则两个线程将无限地等待。在 Python 中这往往发生于以相互冲突的顺序获取多个锁或是循环对依赖项执行 join/await 操作。死锁可通过始终以固定顺序获取多个 锁 来避免。另请参阅 lock 和 reentrant。

 decorator -- 装饰器¶
A function returning another function, usually applied as a function transformation using the
```
@wrapper
```
 syntax. Common examples for decorators are
```
@classmethod
```
 and
```
@staticmethod
```
.
 装饰器语法只是一种语法糖，以下两个函数定义在语义上完全等价:

```
def f(arg):
    ...
f = staticmethod(f)

@staticmethod
def f(arg):
    ...
```

 同样的概念也适用于类，但通常较少这样使用。有关装饰器的详情可参见 函数定义 和 类定义 的文档。

 descriptor -- 描述器¶
任何定义了
```
__get__()
```
,
```
__set__()
```
 或
```
__delete__()
```
 方法的对象。当一个类属性为描述器时，它的特殊绑定行为就会在属性查找时被触发。通常情况下，使用 a.b 来获取、设置或删除一个属性时会在 a 类的字典中查找名称为 b 的对象，但如果 b 是一个描述器，则会调用对应的描述器方法。 理解描述器的概念是更深层次理解 Python 的关键，因为这是许多重要特性的基础，包括函数、方法、特征属性、类方法、静态方法以及对超类的引用等等。
 有关描述器的方法的更多信息，请参阅 实现描述器 或 描述器使用指南。

 dictionary -- 字典¶
一个关联数组，其中的任意键都映射到相应的值。键可以是任何具有
```
__hash__()
```
 和
```
__eq__()
```
 方法的对象。在 Perl 中称为 hash。

 dictionary comprehension -- 字典推导式¶
处理一个可迭代对象中的所有或部分元素并返回结果字典的一种紧凑写法。
```
results = {n: n ** 2 for n in range(10)}
```
 将生成一个由键
```
n
```
 到值
```
n ** 2
```
 的映射构成的字典。参见 列表、集合与字典的显示。

 dictionary view -- 字典视图¶
从
```
dict.keys()
```
,
```
dict.values()
```
 和
```
dict.items()
```
 返回的对象被称为字典视图。它们提供了字典条目的一个动态视图，这意味着当字典改变时，视图也会相应改变。要将字典视图强制转换为真正的列表，可使用
```
list(dictview)
```
。参见 字典视图对象。

 docstring -- 文档字符串¶
作为类、函数或模块之内的第一个表达式出现的字符串字面值。它在代码块被执行时将被忽略，但会被编译器识别并放入所在类、函数或模块的
```
__doc__
```
 属性中。由于它可用于代码内省，因此是存放对象的文档的规范位置。

 duck-typing -- 鸭子类型¶
指一种编程风格，它并不依靠查找对象类型来确定其是否具有正确的接口，而是直接调用或使用其方法或属性（“看起来像鸭子，叫起来也像鸭子，那么肯定就是鸭子。”）由于强调接口而非特定类型，设计良好的代码可通过允许多态替代来提升灵活性。鸭子类型避免使用
```
type()
```
 或
```
isinstance()
```
 检测。(但要注意鸭子类型可以使用 抽象基类 作为补充。) 而往往会采用
```
hasattr()
```
 检测或是 EAFP 编程。

 dunder¶
双下划线 "double underscore" 的非正式简称，在谈及 special method 时使用。 例如，
```
__init__
```
 经常被读作 "dunder init"。

 EAFP¶
“求原谅比求许可更容易”（Easier to Ask for Forgiveness than Permission）的英文缩写。这种 Python 常用代码编写风格会假定所需的键或属性存在，并在假定错误时捕获异常。这种简洁快速风格的特点就是大量运用
```
try
```
 和
```
except
```
 语句。与其相对的则是所谓 LBYL 风格，常见于 C 等许多其他语言。

 evaluate function -- 求值函数¶
一种可被调用来针对某个对象的惰性求值属性进行求值的函数，比如使用
```
type
```
 语句创建的类型别名的值。

 expression -- 表达式¶
可以求出某个值的语法单元。换句话说，一个表达式就是表达元素例如字面值、名称、属性访问、运算符或函数调用的汇总，它们最终都会返回一个值。 与许多其他语言不同，并非所有语言构件都是表达式。还存在不能被用作表达式的 statement，例如
```
while
```
。 赋值也是属于语句而非表达式。

 extension module -- 扩展模块¶
以 C 或 C++ 编写的模块，使用 Python 的 C API 来与语言核心以及用户代码进行交互。

 f-string -- f-字符串¶
f-strings -- f-字符串¶
带有
```
f
```
 或
```
F
```
 前缀的字符串字面值通常被称为 "f-字符串" 即 格式化字符串字面值 的简写。另请参阅 PEP 498。

 file object -- 文件对象¶
对外公开面向文件的 API（带有
```
read()
```
 或
```
write()
```
 等方法）以使用下层资源的对象。 根据其创建方式的不同，文件对象可以处理对真实磁盘文件、其他类型的存储或通信设备的访问（例如标准输入/输出、内存缓冲区、套接字、管道等）。 文件对象也被称为 文件型对象 或 流。
 实际上共有三种类别的文件对象：原始 二进制文件, 缓冲 二进制文件 以及 文本文件。它们的接口定义均在
```
io
```
 模块中。创建文件对象的规范方式是使用
```
open()
```
 函数。

 file-like object -- 文件型对象¶
file object 的同义词。

 filesystem encoding and error handler -- 文件系统编码格式与错误处理器¶
Python 用来从操作系统解码字节串和向操作系统编码 Unicode 的编码格式与错误处理器。
 文件系统编码格式必须保证能成功解码长度在 128 以下的所有字节串。如果文件系统编码格式无法提供此保证，则 API 函数可能会引发
```
UnicodeError
```
.

```
sys.getfilesystemencoding()
```
 和
```
sys.getfilesystemencodeerrors()
```
 函数可被用来获取文件系统编码格式与错误处理器。
 filesystem encoding and error handler 是在 Python 启动时通过
```
PyConfig_Read()
```
 函数来配置的：请参阅
```
PyConfig
```
 的
```
filesystem_encoding
```
 和
```
filesystem_errors
```
 等成员。
 另请参见 locale encoding。

 finder -- 查找器¶
一种会尝试查找被导入模块的 loader 的对象。
 存在两种类型的查找器：元路径查找器 配合
```
sys.meta_path
```
 使用，以及 路径条目查找器 配合
```
sys.path_hooks
```
 使用。
 请参阅 查找器和加载器 和
```
importlib
```
 以了解更多细节。

 floor division -- 向下取整除法¶
向下舍入到最接近的整数的数学除法。向下取整除法的运算符是
```
//
```
。例如，表达式
```
11 // 4
```
 的计算结果是
```
2
```
 ，而与之相反的是浮点数的真正除法返回
```
2.75
```
。注意
```
(-11) // 4
```
 会返回
```
-3
```
 因为这是
```
-2.75
```
 向下 舍入得到的结果。见 PEP 238。

 free threading -- 自由线程¶
一种线程模型，在同一个解释器内部的多个线程可以同时运行 Python 字节码。与此相对的是 global interpreter lock，在同一时刻只允许一个线程执行 Python 字节码。参见 PEP 703。

 free-threaded build -- 自由线程构建版¶
支持 free threading 的 CPython 构建版，在编译之前使用了
```
--disable-gil
```
 选项进行配置。
 另请参阅 Python 对自由线程的支持。

 free variable -- 自由变量¶
在正式场合下，如 语言执行模型 所定义的，自由变量是指在某个命名空间中被使用的不属于该命名空间中的局部变量的任何变量。参见 closure variable 中的样例。在实际应用中，由于
```
codeobject.co_freevars
```
 属性被如此命名，该术语有时也被用作 closure variable 的同义词。

 function -- 函数¶
可以向调用者返回某个值的一组语句。还可以向其传入零个或多个 参数 并在函数体执行中被使用。另见 parameter, method 和 函数定义 等节。

 function annotation -- 函数标注¶
即针对函数形参或返回值的 annotation。
 函数标注通常用于 类型提示: 例如以下函数预期接受两个
```
int
```
 参数并预期返回一个
```
int
```
 值:

```
def sum_two_numbers(a: int, b: int) -> int:
   return a + b
```

 函数标注语法的详解见 函数定义 一节。
 参见 variable annotation 和 PEP 484，其中描述了此功能。另请参阅 注解最佳实践 以了解使用标注的最佳实践。

 __future__¶
future 语句,
```
from __future__ import <feature>
```
 指示编译器使用将在未来的 Python 发布版中成为标准的语法和语义来编译当前模块。
```
__future__
```
 模块文档记录了可能的 feature 取值。 通过导入此模块并对其变量求值，你可以看到每项新特性在何时被首次加入到该语言中以及它将（或已）在何时成为默认:

```
>>> import __future__
>>> __future__.division
_Feature((2, 2, 0, 'alpha', 2), (3, 0, 0, 'alpha', 0), 8192)
```

 garbage collection -- 垃圾收集¶
释放不再被使用的内存空间的过程。 Python 是通过引用计数和一个能够检测和打破循环引用的循环垃圾收集器来执行垃圾收集的。 可以使用
```
gc
```
 模块来控制垃圾收集器。

 generator -- 生成器¶
Informally used to mean either a generator function or a generator iterator, depending on context. The formal terms generator function and generator iterator are uncommon in practice; "generator" alone is almost always sufficient.

 generator function¶
A function which returns a generator object. It looks like a normal function except that it contains
```
yield
```
 expressions for producing a series of values usable in a
```
for
```
-loop or that can be retrieved one at a time with the
```
next()
```
 function. See yield 表达式.

 generator iterator -- 生成器迭代器¶
An object created by a generator function or a generator expression.
 Each
```
yield
```
 temporarily suspends processing, remembering the execution state (including local variables and pending try-statements). When the generator iterator resumes, it picks up where it left off (in contrast to functions which start fresh on every invocation).
 Generator iterators also implement the
```
send()
```
 method to send a value into the suspended generator, and the
```
throw()
```
 method to raise an exception at the point where the generator was paused. See 生成器-迭代器的方法.

 generator expression -- 生成器表达式¶
返回一个 iterator 的 expression。它看起来很像普通表达式后带有定义了一个循环变量、范围的
```
for
```
 子句，以及一个可选的
```
if
```
 子句。以下复合表达式会为外层函数生成一系列值:

```
>>> sum(i*i for i in range(10))         # 平方值 0, 1, 4, ... 81 之和
285
```

 generic function -- 泛型函数¶
为不同的类型实现相同操作的多个函数所组成的函数。在调用时会由调度算法来确定应该使用哪个实现。
 See also the single dispatch glossary entry, the
```
@functools.singledispatch
```
 decorator, and PEP 443.

 generic type -- 泛型¶
可参数化的 type；通常为
```
list
```
 或
```
dict
```
 这样的 容器类。用于 类型提示 和 注解。
 更多细节参见 泛型别名类型、PEP 483、PEP 484、PEP 585 和
```
typing
```
 模块。

 GIL¶
参见 global interpreter lock。

 global interpreter lock -- 全局解释器锁¶
CPython 解释器所采用的一种机制，它确保同一时刻只有一个线程在执行 Python bytecode。此机制通过设置对象模型（包括
```
dict
```
 等重要内置类型）针对并发访问的隐式安全简化了 CPython 实现。给整个解释器加锁使得解释器多线程运行更方便，其代价则是牺牲了在多处理器上的并行性。
 不过，某些标准库或第三方库的扩展模块被设计为在执行计算密集型任务如压缩或哈希时释放 GIL。此外，在执行 I/O 操作时也总是会释放 GIL。
 在 Python 3.13 中，GIL 可以使用
```
--disable-gil
```
 构建配置选项来禁用。在使用此选项构建 Python 之后，代码必须附带
```
-X gil=0
```
 或在设置
```
PYTHON_GIL=0
```
 环境变量后运行。此特性将为多线程应用程序启用性能提升并让高效率地使用多核 CPU 更加容易。要了解详情，请参阅 PEP 703。
 在之前版本的 Python's C API 中，一个函数可能会声明它需要持有 GIL 才能够使用。这被称为具有一个 attached thread state.

 global state -- 全局状态¶
在整个程序中都可访问的数据，如模块级的变量、类变量或 扩展模块 中的 C 静态变量。 在多线程程序中，在线程之间共享全局状态通常需要进行同步以避免 竞争条件 和 数据竞争。

 hash-based pyc -- 基于哈希的 pyc¶
使用对应源文件的哈希值而非最后修改时间来确定其有效性的字节码缓存文件。参见 已缓存字节码的失效。

 hashable -- 可哈希¶
一个对象如果具有在其生命期内绝不改变的哈希值（它需要有
```
__hash__()
```
 方法），并可以同其他对象进行比较（它需要有
```
__eq__()
```
 方法）就被称为 可哈希 对象。可哈希对象必须具有相同的哈希值比较结果才会相等。
 可哈希性使得对象能够作为字典键或集合成员使用，因为这些数据结构要在内部使用哈希值。
 大多数 Python 中的不可变内置对象都是可哈希的；可变容器（例如列表或字典）都不可哈希；不可变容器（例如元组和 frozenset）仅当它们的元素均为可哈希时才是可哈希的。用户定义类的实例对象默认是可哈希的。 它们在比较时一定不相同（除非是与自己比较），它们的哈希值的生成是基于它们的
```
id()
```
。

 IDLE¶
Python 的集成开发与学习环境。 IDLE --- Python 编辑器和 shell 是 Python 标准发行版附带的基本编辑器和解释器环境。

 immortal -- 永生对象¶
永生对象 是在 PEP 683 中引入的 CPython 实现细节。
 如果对象属于永生对象，则它的 reference count 永远不会被修改，因而它在解释器运行期间永远不会被取消分配。 例如，
```
True
```
 和
```
None
```
 在 CPython 中都属于永生对象。
 永生对象可通过
```
sys._is_immortal()
```
，或通过 C API 中的
```
PyUnstable_IsImmortal()
```
 来标识。

 immutable -- 不可变对象¶
具有固定值的对象。不可变对象包括数字、字符串和元组。这样的对象无法被修改。如果需要存储不同的值就必须创建一个新对象。 它们在需要常量哈希值的地方起着重要的作用，例如作为字典的键。不可变对象天然具有 thread-safe 特性因为它们的状态在创建后就不能被修改，这消除了未经适当同步就执行 concurrent modification 的风险。

 import path -- 导入路径¶
由多个位置 (或 路径条目) 组成的列表，会被模块的 path based finder 用来查找导入目标。 在导入时，此位置列表通常来自
```
sys.path
```
，但对次级包来说也可能来自上级包的
```
__path__
```
 属性。

 importing -- 导入¶
令一个模块中的 Python 代码能为另一个模块中的 Python 代码所使用的过程。

 importer -- 导入器¶
查找并加载模块的对象；此对象既属于 finder 又属于 loader。

 index -- 索引¶
一个代表 sequence 中元素位置的数字值。
 在 Python 中，索引是从零开始的。例如，
```
things[0]
```
 指
```
things
```
 中的 第一个 元素；
```
things[1]
```
 指第二个元素。
 在某些上下文中，Python 允许用负索引号表示从序列的末尾开始计数，并可将索引用于 切片。
 另见 subscript。

 interactive -- 交互¶
Python 带有一个交互式解释器，这意味着你可以在解释器提示符后输入语句和表达式，立即执行并查看其结果。只需不带参数地启动
```
python
```
 命令（也可以在你的计算机主菜单中选择相应菜单项）。在测试新想法或检验模块和包的时候这会非常方便（记住
```
help(x)
```
 函数）。 有关交互模式的详情，参见 交互模式。

 interpreted -- 解释型¶
Python 是一种解释型语言，与之相对的是编译型语言，虽然两者的区别由于字节码编译器的存在而会有所模糊。这意味着源文件可以直接运行而不必显式地创建可执行文件再运行。解释型语言通常具有比编译型语言更短的开发/调试周期，但是其程序往往运行得更慢。参见 interactive。

 interpreter shutdown -- 解释器关闭¶
当被要求关闭时，Python 解释器将进入一个特殊运行阶段并逐步释放所有已分配资源，例如模块和各种关键内部结构等。它还会多次调用 垃圾回收器。这会触发用户定义析构器或弱引用回调中的代码执行。在关闭阶段执行的代码可能会遇到各种异常，因为其所依赖的资源已不再有效（常见的例子有库模块或警告机制等）。
 解释器需要关闭的主要原因有
```
__main__
```
 模块或所运行的脚本已完成执行。

 iterable -- 可迭代对象¶
一种能够逐个返回其成员项的对象。可迭代对象的例子包括所有序列类型（如
```
list
```
,
```
str
```
 和
```
tuple
```
 等）以及某些非序列类型如
```
dict
```
, 文件对象 以及任何定义了
```
__iter__()
```
 方法或实现了 sequence 语义的
```
__getitem__()
```
 方法的自定义类的对象。
 可迭代对象可被用于
```
for
```
 循环以及许多其他需要一个序列的地方 (
```
zip()
```
,
```
map()
```
, ...)。 当一个可迭代对象作为参数被传给内置函数
```
iter()
```
 时，它会返回该对象的迭代器。这种迭代器适用于对值集合的一次性遍历。 在使用可迭代对象时，你通常不需要调用
```
iter()
```
 或者自己处理迭代器对象。
```
for
```
 语句会自动为你处理那些操作，创建一个临时的未命名变量用来在循环期间保存迭代器。参见 iterator, sequence 和 generator。

 iterator -- 迭代器¶
用来表示一连串数据流的对象。重复调用迭代器的
```
__next__()
```
 方法 (或将其传给内置函数
```
next()
```
) 将逐个返回流中的项。当没有数据可用时则将引发
```
StopIteration
```
 异常。 到这时迭代器对象中的数据项已耗尽，继续调用其
```
__next__()
```
 方法只会再次引发
```
StopIteration
```
。 迭代器必须具有
```
__iter__()
```
 方法用来返回该迭代器对象自身，因此迭代器必定也是可迭代对象，可被用于其他可迭代对象适用的大部分场合。一个显著的例外是那些会多次重复访问迭代项的代码。 容器对象 (例如
```
list
```
) 在你每次将其传入
```
iter()
```
 函数或是在
```
for
```
 循环中使用时都会产生一个新的迭代器。如果在此情况下你尝试用迭代器则会返回在之前迭代过程中被耗尽的同一迭代器对象，使其看起来就像是一个空容器。
 更多信息可查看 迭代器类型。
  CPython 没有一致应用针对迭代器定义
```
__iter__()
```
 的要求。还要注意 自由线程版 CPython 并不保证迭代器操作的 thread-safe 行为。

 key -- 键¶
在 mapping 中标识条目的值。另见 subscript。

 key function -- 键函数¶
键函数或称整理函数，是能够返回用于排序或排位的值的可调用对象。例如，
```
locale.strxfrm()
```
 可用于生成一个符合特定区域排序约定的排序键。
 Python 中有许多工具都允许用键函数来控制元素的排位或分组方式。其中包括
```
min()
```
,
```
max()
```
,
```
sorted()
```
,
```
list.sort()
```
,
```
heapq.merge()
```
,
```
heapq.nsmallest()
```
,
```
heapq.nlargest()
```
 以及
```
itertools.groupby()
```
。
 键函数有多个创建方式。例如，
```
str.casefold()
```
 方法可以用作忽略大小写排序的键函数。或者，键函数也可通过
```
lambda
```
 表达式如
```
lambda r: (r[0], r[2])
```
 来创建。 此外，
```
operator.attrgetter()
```
,
```
operator.itemgetter()
```
 和
```
operator.methodcaller()
```
 是三个键函数构造器。请参阅 排序指引 来获取创建和使用键函数的示例。

 keyword argument -- 关键字参数¶
参见 argument。

 lambda¶
由一个单独 expression 构成的匿名内联函数，表达式会在调用时被求值。创建 lambda 函数的句法为
```
lambda [parameters]: expression
```

 LBYL¶
“先看后跳”（Look Before You Leap）的英文缩写。这种代码编写风格会在进行调用或查找之前显式地检查前提条件。此风格与 EAFP 方式恰成对比，其特点是大量使用
```
if
```
 语句。
 在多线程环境中，LBYL 方式会有在“查看”和“跳跃”之间引入 race condition 的风险。例如，以下代码
```
if key in mapping: return mapping[key]
```
 可能由于在检测操作之后其他线程将 key 从 mapping 中移除而出错。这种问题可通过 锁 或使用 EAFP 方式来解决。另请参阅 thread-safe.

 lexical analyzer -- 词法分析器¶
分词器 的正式名称；参见 token。

 list -- 列表¶
一种 Python 内置 sequence。虽然名为列表，但它更类似于其他语言中的数组而非链表，因为访问元素的时间复杂度为 O(1)。

 list comprehension -- 列表推导式¶
处理一个序列中的所有或部分元素并返回结果列表的一种紧凑写法。
```
result = ['{:#04x}'.format(x) for x in range(256) if x % 2 == 0]
```
 将生成一个 0 到 255 范围内的十六进制偶数对应字符串（0x..）的列表。其中
```
if
```
 子句是可选的，如果省略则
```
range(256)
```
 中的所有元素都会被处理。

 lock -- 锁¶
表示在同一时刻只允许一个线程访问共享资源的 synchronization primitive。 一个线程在访问受保护的资源之前必须获取锁并在之后释放锁。如果一个线程试图获取已被另一个线程持有的锁，它将被阻塞直到锁可用。Python 的
```
threading
```
 模块提供了
```
Lock
```
 (基础锁) 和
```
RLock
```
 (reentrant 锁)。锁被用于防止 竞争条件 并确保对共享数据的 thread-safe 访问。 对于加锁也存在其他设计模式如队列、生产者/消费者模式以及线程局部状态等。另请参阅 deadlock 和 reentrant.

 lock-free -- 免加锁¶
不需要任何 lock 而是使用原子化 CPU 指令来确保正确性的操作。 免加锁操作可以并发地执行而不会相互阻塞也不能被持有所的操作所阻塞。 在 自由线程 Python 中，内置类型如
```
dict
```
 和
```
list
```
 均提供免加锁读取操作，这意味着在多步骤修改期间即使这些修改持有 per-object lock 其他线程也可能观察到中间状态。

 loader -- 加载器¶
负责加载模块的对象。它必须定义
```
exec_module()
```
 和
```
create_module()
```
 方法以实现
```
Loader
```
 接口。加载器通常由一个 finder 返回。另请参阅：

- 查找器和加载器

-
```
importlib.abc.Loader
```

- PEP 302

 locale encoding -- 语言区域编码格式¶
在 Unix 上，它是 LC_CTYPE 语言区域的编码格式。它可以通过
```
locale.setlocale(locale.LC_CTYPE, new_locale)
```
 来设置。
 在 Windows 上，它是 ANSI 代码页 (如:
```
"cp1252"
```
)。
 在 Android 和 VxWorks 上，Python 使用
```
"utf-8"
```
 作为语言区域编码格式。

```
locale.getencoding()
```
 可被用来获取语言区域编码格式。
 另请参阅 filesystem encoding and error handler。

 magic method -- 魔术方法¶
special method 的非正式同义词。

 mapping -- 映射¶
一种支持任意键查找并实现了
```
collections.abc.Mapping
```
 或
```
collections.abc.MutableMapping
```
 抽象基类 所规定方法的容器对象。 此类对象的例子包括
```
dict
```
,
```
collections.defaultdict
```
,
```
collections.OrderedDict
```
 以及
```
collections.Counter
```
。

 meta path finder -- 元路径查找器¶
```
sys.meta_path
```
 的搜索所返回的 finder。元路径查找器与 path entry finders 存在关联但并不相同。
 请查看
```
importlib.abc.MetaPathFinder
```
 了解元路径查找器所实现的方法。

 metaclass -- 元类¶
一种用于创建类的类。类定义包含类名、类字典和基类列表。元类负责接受上述三个参数并创建相应的类。大部分面向对象的编程语言都会提供一个默认实现。Python 的特别之处在于可以创建自定义元类。大部分用户永远不需要这个工具，但当需要出现时，元类可提供强大而优雅的解决方案。它们已被用于记录属性访问日志、添加线程安全性、跟踪对象创建、实现单例，以及其他许多任务。
 更多详情参见 元类。

 method -- 方法¶
在类内部定义的函数。如果作为该类的实例的一个属性来调用，方法将会获取实例对象作为其第一个 argument (通常命名为
```
self
```
)。参见 function 和 nested scope。

 method resolution order -- 方法解析顺序¶
方法解析顺序就是在查找成员时搜索基类的顺序。请参阅 Python 2.3 方法解析顺序 了解自 2.3 发布版起 Python 解释器所使用算法的详情。

 module -- 模块¶
此对象是 Python 代码的一种组织单位。各模块具有独立的命名空间，可包含任意 Python 对象。模块可通过 importing 操作被加载到 Python 中。
 另见 package。

 module spec -- 模块规格¶
一个命名空间，其中包含用于加载模块的相关导入信息。是
```
importlib.machinery.ModuleSpec
```
 的实例。
 另请参阅 模块规格说明。

 MRO¶
参见 method resolution order。

 mutable -- 可变对象¶
一种带有在程序运行期间允许修改的状态的 object。在多线程的程序中，在线程之间共享的可变对象需要谨慎地同步操作以避免 竞争条件。另请参阅 immutable, thread-safe 和 concurrent modification.

 named tuple -- 具名元组¶
术语“具名元组”可用于任何继承自元组，并且其中的可索引元素还能使用名称属性来访问的类型或类。这样的类型或类还可能拥有其他特性。
 有些内置类型属于具名元组，包括
```
time.localtime()
```
 和
```
os.stat()
```
 的返回值。另一个例子是
```
sys.float_info
```
:

```
>>> sys.float_info[1]                   # 索引访问
1024
>>> sys.float_info.max_exp              # 命名字段访问
1024
>>> isinstance(sys.float_info, tuple)   # 属于元组
True
```

 有些具名元组是内置类型（比如上面的例子）。此外，具名元组还可通过常规类定义从
```
tuple
```
 继承并定义指定名称的字段的方式来创建。 这样的类可以手工编写，或者也可以通过继承
```
typing.NamedTuple
```
，或者使用工厂函数
```
collections.namedtuple()
```
 来创建。后一种方式还会添加一些手工编写或内置的具名元组所没有的额外方法。

 namespace -- 命名空间¶
命名空间是存放变量的场所。命名空间有局部、全局和内置的，还有对象中的嵌套命名空间（在方法之内）。命名空间通过防止命名冲突来支持模块化。例如，函数
```
builtins.open
```
 与
```
os.open()
```
 可通过各自的命名空间来区分。命名空间还通过明确哪个模块实现那个函数来帮助提高可读性和可维护性。例如，
```
random.seed()
```
 或
```
itertools.islice()
```
 这种写法明确了这些函数是由
```
random
```
 与
```
itertools
```
 模块分别实现的。

 namespace package -- 命名空间包¶
一种仅被用作子包的容器的 package。命名空间包可以没有实体表示物，具体而言就是不同于 regular package 因为它们没有
```
__init__.py
```
 文件。
 命名空间包允许几个可单独安装的包具有共同的父包。在其他情况下，则推荐使用 regular package。
 要了解更多信息，请参阅 PEP 420 和 命名空间包。
 另可参见 module。

 native code -- 原生代码¶
编译为机器指令并直接在处理器上运行的代码，这与在虚拟机上解释或运行的代码相对。在 Python 的上下文中，原生代码通常是指 扩展模块中 可以被 Python 调用的 C, C++, Rust 或 Fortran 代码。另请参阅 extension module.

 nested scope -- 嵌套作用域¶
在一个定义范围内引用变量的能力。例如，在另一函数之内定义的函数可以引用前者的变量。请注意嵌套作用域默认只对引用有效而对赋值无效。局部变量的读写都受限于最内层作用域。类似的，全局变量的读写则作用于全局命名空间。通过
```
nonlocal
```
 关键字可允许写入外层作用域。

 new-style class -- 新式类¶
对目前已被应用于所有类对象的类形式的旧称谓。在较早的 Python 版本中，只有新式类能够使用 Python 新增的更灵活的特性，如
```
__slots__
```
、描述器、特征属性、
```
__getattribute__()
```
、类方法和静态方法等。

 non-deterministic -- 非确定性的¶
程序以相同的输入多次执行时可能存在不同的行为。在多线程的程序中，非确定性的行为往往来自于线程的相对用时或交替影响结果的 竞争条件。使用 锁 或其他 同步原语 进行正确的同步操作有助于保证确定性的行为。

 object -- 对象¶
任何具有状态（属性或值）以及预定义行为（方法）的数据。object 也是任何 new-style class 的最顶层基类名。

 optimized scope -- 已优化的作用域¶
当代码被编译时编译器已充分知晓目标局部变量名称的作用域，这允许对这些名称的读写进行优化。 针对函数、生成器、协程、推导式和生成器表达式的局部命名空间都是这样的已优化作用域。 注意：大部分解释器优化将应用于所有作用域，只有那些依赖于已知的局部和非局部变量名称集合的优化会仅限于已优化的作用域。

 optional module -- 可选模块¶
一个属于 standard library 组成部分的 extension module，但可能不存在于某些 CPython 构建版中，通常是由于缺少某个第三方库或由于该模块在给定的平台上不可用。
 请参阅 针对可选模块的要求 查看需要第三方库的可选模块列表。

 package -- 包¶
一种可包含子模块或递归地包含子包的 Python module。从技术上说，包是具有
```
__path__
```
 属性的 Python 模块。
 另参见 regular package 和 namespace package。

 parallelism -- 并行¶
同时执行多个操作（例如在多个 CPU 核心上）。在启用 全局解释器锁 (GIL) 的 Python 构建版中，在同一时刻只能有一个线程在运行 Python 字节码，因此想发挥多个 CPU 核心的能力通常要使用多个进程 (例如通过
```
multiprocessing
```
) 或者使用释放 GIL 的原生扩展。在 自由线程 Python 构建版中，多个 Python 线程可以在不同的核心上同时运行 Python 代码。

 parameter -- 形参¶
function (或方法) 定义中的命名实体，它指定函数可以接受的一个 argument (或在某些情况下，是多个参数)。 共有有五种形参：

- positional-or-keyword: 位置或关键字，指定一个可以作为 位置参数 传入也可以作为 关键字参数 传入的实参。这是默认的形参类型，例如下面的 foo 和 bar:

```
def func(foo, bar=None): ...
```

- positional-only: 仅限位置，指定一个只能通过位置传入的参数。仅限位置形参可通过在函数定义的形参列表中它们之后包含一个
```
/
```
 字符来定义，例如下面的 posonly1 和 posonly2:

```
def func(posonly1, posonly2, /, positional_or_keyword): ...
```

- keyword-only: 仅限关键字，指定一个只能通过关键字传入的参数。仅限关键字形参可通过在函数定义的形参列表中包含单个可变位置形参或者在多个可变位置形参之前放一个
```
*
```
 来定义，例如下面的 kw_only1 和 kw_only2:

```
def func(arg, *, kw_only1, kw_only2): ...
```

- var-positional：可变位置，指定可以提供由一个任意数量的位置参数构成的序列（附加在其他形参已接受的位置参数之后）。这种形参可通过在形参名称前加缀
```
*
```
 来定义，例如下面的 args:

```
def func(*args, **kwargs): ...
```

- var-keyword：可变关键字，指定可以提供任意数量的关键字参数（附加在其他形参已接受的关键字参数之后）。这种形参可通过在形参名称前加缀
```
**
```
 来定义，例如上面的 kwargs。

 形参可以同时指定可选和必选参数，也可以为某些可选参数指定默认值。
 另参见 argument 术语表条目、参数与形参的区别 中的常见问题、
```
inspect.Parameter
```
 类、函数定义 一节以及 PEP 362。

 per-object lock -- 每对象锁¶
关联到单独对象实例的 lock 而不是由所有对象共享的全局锁。 在 自由线程 Python 中，内置类型如
```
dict
```
 和
```
list
```
 均使用每对象锁以允许在不同对象上并发操作同时在同一对象上序列化操作。 持有每对象锁的操作可防止在同一对象上其他加锁操作的执行，但不会阻塞 lock-free 操作。

 path entry -- 路径入口¶
import path 中的一个单独位置，会被 path based finder 用来查找要导入的模块。

 path entry finder -- 路径入口查找器¶
任一可调用对象使用
```
sys.path_hooks
```
 (即 path entry hook) 返回的 finder，此种对象能通过 path entry 来定位模块。
 请参看
```
importlib.abc.PathEntryFinder
```
 以了解路径入口查找器所实现的各个方法。

 path entry hook -- 路径入口钩子¶
一种可调用对象，它在知道如何查找特定 path entry 中的模块的情况下能够使用
```
sys.path_hooks
```
 列表返回一个 path entry finder。

 path based finder -- 基于路径的查找器¶
默认的一种 元路径查找器，可在一个 import path 中查找模块。

 path-like object -- 路径型对象¶
代表一个文件系统路径的对象。路径类对象可以是一个表示路径的
```
str
```
 或者
```
bytes
```
 对象，还可以是一个实现了
```
os.PathLike
```
 协议的对象。一个支持
```
os.PathLike
```
 协议的对象可通过调用
```
os.fspath()
```
 函数转换为
```
str
```
 或者
```
bytes
```
 类型的文件系统路径；
```
os.fsdecode()
```
 和
```
os.fsencode()
```
 可被分别用来确保获得
```
str
```
 或
```
bytes
```
 类型的结果。此对象是由 PEP 519 引入的。

 PEP¶
“Python 增强提议”的英文缩写。一个 PEP 就是一份设计文档，用来向 Python 社区提供信息，或描述一个 Python 的新增特性及其进度或环境。PEP 应当提供精确的技术规格和所提议特性的原理说明。
 PEP 应被作为提出主要新特性建议、收集社区对特定问题反馈以及为必须加入 Python 的设计决策编写文档的首选机制。PEP 的作者有责任在社区内部建立共识，并应将不同意见也记入文档。
 参见 PEP 1。

 portion -- 部分¶
构成一个命名空间包的单个目录内文件集合（也可能存放于一个 zip 文件内），具体定义见 PEP 420。

 positional argument -- 位置参数¶
参见 argument。

 provisional API -- 暂定 API¶
暂定 API 是指被有意排除在标准库的向后兼容性保证之外的应用编程接口。虽然此类接口通常不会再有重大改变，但只要其被标记为暂定，就可能在核心开发者确定有必要的情况下进行向后不兼容的更改（甚至包括移除该接口）。此种更改并不会随意进行 -- 仅在 API 被加入之前未考虑到的严重基础性缺陷被发现时才可能会这样做。
 即便是对暂定 API 来说，向后不兼容的更改也会被视为“最后的解决方案” —— 任何问题被确认时都会尽可能先尝试找到一种向后兼容的解决方案。
 这种处理过程允许标准库持续不断地演进，不至于被有问题的长期性设计缺陷所困。详情见 PEP 411。

 provisional package -- 暂定包¶
参见 provisional API。

 Python 3000¶
Python 3.x 发布路线的昵称（这个名字在版本 3 的发布还遥遥无期的时候就已出现了）。有时也被缩写为“Py3k”。

 Pythonic¶
指一个思路或一段代码紧密遵循了 Python 语言最常用的风格和理念，而不是使用其他语言中通用的概念来实现代码。例如，Python 的常用风格是使用
```
for
```
 语句循环来遍历一个可迭代对象中的所有元素。许多其他语言没有这样的结构，因此不熟悉 Python 的人有时会选择使用一个数字计数器:

```
for i in range(len(food)):
    print(food[i])
```

 而相应的更简洁更 Pythonic 的方法是这样的:

```
for piece in food:
    print(piece)
```

 qualified name -- 限定名称¶
一个以点号分隔的名称，显示从模块的全局作用域到该模块中定义的某个类、函数或方法的“路径”，相关定义见 PEP 3155。对于最高层级的函数和类，限定名称与对象名称一致:

```
>>> class C:
...     class D:
...         def meth(self):
...             pass
...
>>> C.__qualname__
'C'
>>> C.D.__qualname__
'C.D'
>>> C.D.meth.__qualname__
'C.D.meth'
```

 当被用于引用模块时，完整限定名称 意为标示该模块的以点号分隔的整个路径，其中包含其所有的父包，例如
```
email.mime.text
```
:

```
>>> import email.mime.text
>>> email.mime.text.__name__
'email.mime.text'
```

 race condition -- 竞争条件¶
一个程序的行为取决于事件的相对时长和事件顺序的情况，特别是在多线程的程序当中。 竞争条件可能导致 non-deterministic 的行为以及难以重现的程序缺陷。 data race 是涉及对共享内存的未同步访问的一种特定类型的竞争条件。 LBYL 代码风格特别容易在多线程代码中造成竞争条件。 使用 锁 和其他 同步原语 有助于防止竞争条件。helps prevent race conditions.

 reference count -- 引用计数¶
指向某个对象的引用的数量。当一个对象的引用计数降为零时，它就会被释放。特殊的 immortal 对象具有永远不会被修改的引用计数，因此这种对象永远不会被释放。引用计数对 Python 代码来说通常是不可见的，但它是 CPython 实现的一个关键元素。程序员可以调用
```
sys.getrefcount()
```
 函数来返回特定对象的引用计数。
 在 CPython 中，引用计数并非稳定或明确定义的值；对象的引用数量以及该数量受 Python 代码影响的方式，可能会因版本不同而有所差异。

 regular package -- 常规包¶
传统型的 package，例如包含有一个
```
__init__.py
```
 文件的目录。
 另参见 namespace package。

 reentrant -- 重进入¶
一个函数的特征属性或 lock，它允许被同一个线程多次调用或者获取而不会导致错误或 deadlock。
 对于函数来说，重进入意味着该函数可以在之前的唤起完成之前安全地被再次调用，这在函数可能被递归地调用或被信号处理器调用时是很重要的。 线程不安全的函数如果在多线程的程序中以重进入方式被调用则可能导致 non-deterministic。
 对于锁来说，Python 的
```
threading.RLock
```
 (重进入锁) 是支持重进入的，这意味着已经持有某个锁的线程可以再次获取它而不造成阻塞。与此相反，
```
threading.Lock
```
 是不支持重进入的 —— 试图从同一个线程再次获取它会导致死锁。
 另请参阅 lock 和 deadlock。

 REPL¶
“读取 - 求值 - 打印循环”read-eval-print loop 的缩写，interactive 解释器 shell 的另一个名字。

 __slots__¶
一种写在类内部的声明，通过预先声明实例属性等对象并移除实例字典来节省内存。虽然这种技巧很流行，但想要用好却并不容易，最好是只保留在少数情况下采用，例如极耗内存的应用程序，并且其中包含大量实例。

 sequence -- 序列¶
一种 iterable，它支持通过
```
__getitem__()
```
 特殊方法来使用整数索引进行高效的元素访问，并定义了一个返回序列长度的
```
__len__()
```
 方法。内置序列类型有
```
list
```
,
```
str
```
,
```
tuple
```
 和
```
bytes
```
 等。请注意虽然
```
dict
```
 也支持
```
__getitem__()
```
 和
```
__len__()
```
，但它被归类为映射而非序列，因为它使用任意的 hashable 键而不是整数来查找元素。

```
collections.abc.Sequence
```
 抽象基类定义了一个更丰富的接口，它在
```
__getitem__()
```
 和
```
__len__()
```
 之外，还添加了
```
count()
```
,
```
index()
```
,
```
__contains__()
```
 和
```
__reversed__()
```
。实现此扩展接口的类型可以使用
```
register()
```
 来显式地注册。要获取有关通用序列方法的更多文档，请参阅 通用序列操作.

 set comprehension -- 集合推导式¶
处理一个可迭代对象中的所有或部分元素并返回结果集合的一种紧凑写法。
```
results = {c for c in 'abracadabra' if c not in 'abc'}
```
 将生成字符串集合
```
{'r', 'd'}
```
。参见 列表、集合与字典的显示。

 single dispatch -- 单分派¶
一种 generic function 分派形式，其实现是基于单个参数的类型来选择的。

 slice -- 切片¶
类型为
```
slice
```
 的对象，用于表示 sequence 的一部分。切片对象是在使用 抽取标记法 的 切片 形式时创建的，即在方括号内带冒号，比如
```
variable_name[1:3:5]
```
。

 soft deprecated -- 软弃用¶
被软弃用的 API 不应在新编写的代码中使用，但在已有代码中使用仍是安全的。这样的 API 将保留在文档中并被测试，但不会再获得进一步的功能增强。
 与普通的弃用不同，软弃用没有 API 移除计划也不会发出弃用警告。
 参见 PEP 387: Soft Deprecation。

 special method -- 特殊方法¶
一种由 Python 隐式调用的方法，用来对某个类型执行特定操作例如相加等等。这种方法的名称的首尾都为双下划线。特殊方法的文档参见 特殊方法名称。

 standard library -- 标准库¶
作为官方 Python 解释器软件包的组成部分一同发布的 包, 模块 和 扩展模块 集合。该集合成员的实际内容可能因系统平台、可用系统库或其他条件的不同而发生变化。 相关文档可在 Python 标准库 查看。
 另请参阅
```
sys.stdlib_module_names
```
 获取所有可用标准库模块名称的列表。

 statement -- 语句¶
语句是程序段（一个代码“块”）的组成单位。一条语句可以是一个 expression 或某个带有关键字的结构，例如
```
if
```
、
```
while
```
 或
```
for
```
。

 static type checker -- 静态类型检查器¶
读取 Python 代码并进行分析，以查找问题例如不正确的类型的外部工具。另请参阅 类型提示 以及
```
typing
```
 模块。

 stdlib -- 标准库¶
standard library 的缩写。

 steal¶
In Python's C API, "stealing" an argument means that ownership of the argument is transferred to the called function. The caller must not use that reference after the call. Generally, functions that "steal" an argument do so even if they fail.
 See 引用计数细节 for a full explanation.

 strong reference -- 强引用¶
在 Python 的 C API 中，强引用是指为持有引用的代码所拥有的对象的引用。在创建引用时可通过调用
```
Py_INCREF()
```
 来获取强引用而在删除引用时可通过
```
Py_DECREF()
```
 来释放它。

```
Py_NewRef()
```
 函数可被用于创建一个对象的强引用。通常，必须在退出某个强引用的作用域时在该强引用上调用
```
Py_DECREF()
```
 函数，以避免引用的泄漏。
 另请参阅 borrowed reference。

 subscript -- 下标¶
下标表达式 在方括号中的表达式，例如，在
```
items[3]
```
 中的
```
3
```
。 通常用于选择抽取容器中的一个元素。在抽取 mapping 时也称 key，在抽取 sequence 时也称 index。

 synchronization primitive -- 同步化原语¶
用于协调（同步）多线程执行以确保对共享资源的 thread-safe 访问的基础构造单元。Python 的
```
threading
```
 模块提供了多种同步化原语包括
```
Lock
```
,
```
RLock
```
,
```
Semaphore
```
,
```
Condition
```
,
```
Event
```
 和
```
Barrier
```
。此外，
```
queue
```
 模块提供了特别适用于多线程的程序的多生产者、多消费者队列。 这些原语有助于防止 竞争条件 并协调线程执行。另请参阅 lock。

 t-string -- t-字符串¶
t-strings -- t-字符串¶
带有
```
t
```
 或
```
T
```
 前缀的字符串字面值通常被称为 "t-字符串" 即 模板字符串字面值 的简写。

 text encoding -- 文本编码格式¶
在 Python 中，一个字符串是一串 Unicode 代码点 (范围为
```
U+0000
```
--
```
U+10FFFF
```
)。 为了存储或传输一个字符串，它需要被序列化为一串字节。
 将一个字符串序列化为一个字节序列被称为“编码”，而从字节序列中重新创建字符串被称为“解码”。
 有各种不同的文本序列化 编码器，它们被统称为 "文本编码格式"。

 text file -- 文本文件¶
一种能够读写
```
str
```
 对象的 file object。通常一个文本文件实际是访问一个面向字节的数据流并自动处理 text encoding。 文本文件的例子包括以文本模式 (
```
'r'
```
 或
```
'w'
```
) 打开的文件、
```
sys.stdin
```
、
```
sys.stdout
```
 以及
```
io.StringIO
```
 的实例。
 另请参看 binary file 了解能够读写 字节型对象 的文件对象。

 thread state -- 线程状态¶
CPython 运行时在一个 OS 线程中运行所使用的信息。例如，这包括可能存在的当前异常，以及字节码解释器的状态等。
 每个线程状态将绑定到一个单独的 OS 线程，但线程可能具有许多可用的线程状态。在最一般情况下，可能立即 附加 它们中的一个。
 调用大多数 Python 的 C API 都需要有一个 attached thread state，除非一个函数文档显式地写明了不同情况。字节码解释器只能运行在一个已附加线程状态下。
 每个线程状态都归属于一个单独的解释器，但每个解释器可能有多个线程状态，包括同一个 OS 线程的多个线程状态。 来自多个解释器的线程状态可能会绑定到相同的线程，但在任一给定时刻在一个线程中只能有一个线程状态可以被 附加。
 请参阅 线程状态和全局解释器锁 了解详情。

 thread-safe -- 线程安全¶
当被多个线程并发地使用时保持正确行为的模块、函数或类。线程安全的代码会使用适当的 同步化原语 如 锁 来保护共享的可变状态，或是被设计为能完全避免共享的可变状态。在 自由线程 构建版中，内置类型如
```
dict
```
,
```
list
```
 和
```
set
```
 会使用内部锁实现各种操作的线程安全，不过这并不绝对保证线程安全。在多线程程序中使用非线程安全的代码时可能会出现 竞争条件 和 数据竞争 等问题。

 token -- 词元¶
一个源代码小单元，由 词法分析器 (或称 分词器) 生成。名称、数字、字符串、运算符、换行符等均由词元来表示。

```
tokenize
```
 模块对外暴露了 Python 的词法分析器。
```
token
```
 模块包含了有关各种词元类型的信息。

 triple-quoted string -- 三引号字符串¶
首尾各带三个连续双引号（"）或者单引号（'）的字符串。它们在功能上与首尾各用一个引号标注的字符串没有什么不同，但是有多种用处。它们允许你在字符串内包含未经转义的单引号和双引号，并且可以跨越多行而无需使用连接符，在编写文档字符串时特别好用。

 type -- 类型¶
Python 对象的类型决定它属于什么种类；每个对象都具有特定的类型。对象的类型可通过其
```
__class__
```
 属性来访问或是用
```
type(obj)
```
 来获取。

 type alias -- 类型别名¶
一个类型的同义词，创建方式是把类型赋值给特定的标识符。
 类型别名的作用是简化 类型注解。例如:

```
def remove_gray_shades(
        colors: list[tuple[int, int, int]]) -> list[tuple[int, int, int]]:
    pass
```

 可以这样提高可读性:

```
Color = tuple[int, int, int]

def remove_gray_shades(colors: list[Color]) -> list[Color]:
    pass
```

 参见
```
typing
```
 和 PEP 484，其中有对此功能的详细描述。

 type hint -- 类型提示¶
annotation 为变量、类属性、函数的形参或返回值指定预期的类型。
 类型提示是可选的而不是 Python 的强制要求，但它们对 静态类型检查器 很有用处。 它们还能协助 IDE 实现代码补全与重构。
 全局变量、类属性和函数的类型注解可以使用
```
typing.get_type_hints()
```
 来访问，但局部变量则不可以。
 参见
```
typing
```
 和 PEP 484，其中有对此功能的详细描述。

 universal newlines -- 通用换行¶
一种解读文本流的方式，将以下所有符号都识别为行结束标志：Unix 的行结束约定
```
'\n'
```
、Windows 的约定
```
'\r\n'
```
 以及旧版 Macintosh 的约定
```
'\r'
```
。参见 PEP 278 和 PEP 3116 和
```
bytes.splitlines()
```
 了解更多用法说明。

 variable annotation -- 变量标注¶
对变量或类属性的 annotation。
 在标注变量或类属性时，还可选择为其赋值:

```
class C:
    field: 'annotation'
```

 变量标注通常被用作 类型提示：例如以下变量预期接受
```
int
```
 类型的值:

```
count: int = 0
```

 变量标注语法的详细解释见 带标注的赋值语句 一节。
 参见 function annotation, PEP 484 和 PEP 526，其中描述了此功能。另请参阅 注解最佳实践 以了解使用标注的最佳实践。

 virtual environment -- 虚拟环境¶
一种采用协作式隔离的运行时环境，允许 Python 用户和应用程序在安装和升级 Python 分发包时不会干扰到同一系统上运行的其他 Python 应用程序的行为。
 另参见
```
venv
```
。

 virtual machine -- 虚拟机¶
一台完全通过软件定义的计算机。Python 虚拟机可执行字节码编译器所生成的 bytecode。

 walrus operator -- 海象运算符¶
对于 赋值表达式 运算符
```
:=
```
 的玩笑性称谓，因为如果你侧头看它会有点像一只海象。

 Zen of Python -- Python 之禅¶
列出 Python 设计的原则与哲学，有助于理解与使用这种语言。查看其具体内容可在交互模式提示符中输入 "
```
import this
```
"。

#### 上一主题
 弃用

#### 下一主题
 关于本文档

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

- 术语对照表

-
 |

-   主题  自动 明亮 黑暗   |

  © 版权 2001 Python Software Foundation.  本页面采用 Python 软件基金会许可证第 2 版授权。  文档中的示例、代码片段及其他代码内容额外采用零条款 BSD 许可证授权。  更多信息请参阅《 历史与许可 》。  Python 软件基金会是一家非营利性公司。 请进行捐赠。   最后更新于8月 05, 2026 (11:17 UTC) 。 发现了错误？  使用Sphinx 8.2.3 创建。
