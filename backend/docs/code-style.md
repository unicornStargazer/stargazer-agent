# Backend 自定义代码规范检查

检查器为 `backend/scripts/check_code_style.py`，仅依赖 Python 标准库，要求 Python 3.12+。使用 AST 判断语义位置，使用 tokenize 配对括号并检查物理行；不会把注释、字符串中的括号当作代码，也不按整条语句的结束行粗略判断参数列表。检查器与对应测试也必须通过这些规则。

## 使用

从仓库根目录运行：

```sh
python backend/scripts/check_code_style.py
python backend/scripts/check_code_style.py backend/src/example.py backend/tests
python backend/scripts/check_code_style.py backend --exclude generated
python -m pytest backend/tests/architecture/test_code_style_checker.py -q
```

未提供路径时，扫描脚本所在 backend 下的 `src`、`tests`、`examples`、`scripts`，与当前工作目录无关。显式路径相对于当前工作目录解析；目录递归扫描 `.py`，重复路径去重。默认排除目录名 `.venv`、`venv`、`env`、`.git`、`__pycache__`、`.mypy_cache`、`.pytest_cache`、`.ruff_cache`、`.tox`、`.nox`、`node_modules`、`build`、`dist`、`site-packages`；`--exclude NAME` 可重复，追加按目录名排除，显式指定排除目录中的文件也会跳过。目录软链接不会递归跟随。

输出格式为 `path:line:code: message`（行号从 1 开始），最后打印检查文件数与违规数。通过退出 0；发现规则违规、语法错误、路径不存在、读取/编码错误退出 1；命令行参数错误由 argparse 退出 2。单个文件失败不阻止其余文件检查。读取文件遵循 Python encoding cookie 和 UTF-8 BOM。

这不是格式化器，不修改文件，也不替代类型检查或 Ruff。`test_all_backend_python_follows_code_style` 架构测试会扫描全部四个默认目录，作为 pytest 中的规范门禁，而不仅验证示例片段。没有存量代码白名单、`noqa` 或任意忽略单行的机制。不要运行格式化器去重新拆分这些刻意保持单行的参数列表。

## 规则

### CS001：自定义函数最多 4 个参数

检查所有 `def` / `async def`，包括嵌套函数与方法。位置参数、仅位置参数、仅关键字参数都计数；普通参数名为 `self` / `cls` 时不计数。`*args`、`**kwargs` 各算一个，无论其名称是否恰为 `self` / `cls`。`/`、单独的 `*` 分隔符不计数。Lambda 不属于本条自定义 def 检查范围；类定义基类列表也不是函数参数列表。

```python
# 通过：4 个业务参数
async def execute(self, first, second, *args, **kwargs): pass

# 拒绝：5 个业务参数
async def execute(self, first, second, third, *args, **kwargs): pass
```

### CS002：定义的参数列表单行

从 `def` / `async def` 开始行到参数列表的闭合 `)` 必须在同一物理行。包括空参数、默认值、参数注解；反斜杠续行也不能绕过。PEP 695 类型参数中的括号不会被误当作普通参数列表。

**返回类型注解不属于参数列表**，允许单独跨行；函数体当然也允许跨行。不检查任意行长，不要求整个函数定义语句都在一行。

```python
def describe(value) -> tuple[
    int,
    str,
]:
    pass
```

### CS003：调用的参数列表单行

每个 AST Call 的参数括号从 `(` 到对应的 `)` 必须在同一物理行，包括空调用、星号展开、关键字参数以及嵌套容器。注释、三引号字符串、反斜杠续行都不会放宽此要求。只限制参数列表，不额外要求被调用表达式的所有部分均单行。

应先定义多行数据，再传变量：

```python
options = {
    "first": 1,
    "second": 2,
}
result = execute(options)
```

### CS004：调用结果先承接，后消费

调用（包括构造对象、内置函数、方法）的结果只有以下直接父级语法位置允许：

- `Assign`、`AnnAssign`、`NamedExpr` 的**整个 value** 是调用；支持链式赋值、解包赋值与海象运算符。
- 上述 value 是直接 `await call()`，即 `result = await fetch()` 等。
- 独立副作用表达式 `call()` 或独立 `await call()`，结果被丢弃。
- `raise Error(...)` 中直接异常构造，仅豁免外层 Call；例如 `raise Error(fetch())` 的内部 `fetch()` 仍必须先提取。`raise ... from factory()` 中的 cause 调用不豁免。
- 下文明确列出的声明式例外。

这是语法约束，不追踪运行时返回值或推断函数是否仅有副作用，不做变量的数据流分析。Assign/AnnAssign 的目标形式不另外限制（例如属性赋值、下标赋值）；若目标表达式本身含调用，该调用仍要独立检查。关键是先用赋值承接**整个**调用结果；把调用埋进某个更大的赋值表达式并不能通过。

以下均拒绝：

```python
return fetch()
yield fetch()
yield from fetch()
for item in fetch(): pass
if fetch(): pass
with acquire() as resource: pass
consume(fetch())
result = fetch().attribute
result = fetch()[0]
result = fetch() + 1
result = [fetch()]
result = f"{fetch()}"
```

同样拒绝 `async for ... in call()`、`async with call()`、`return await call()`、`yield await call()`、生成式/推导式中的未承接调用、条件表达式、断言等。外层调用被赋值，并不豁免内层调用。异常构造遵循上面的窄例外，不泛化到其他表达式。

应写成：

```python
value = fetch()
consume(value)

manager = acquire()
with manager as resource:
    use(resource)

async def task():
    manager = acquire_async()
    async with manager as resource:
        result = await fetch_async(resource)
    return result
```

`with ... as resource` 的绑定发生在进入上下文后，**不算先承接 context manager 调用结果**；普通/异步上下文都必须先绑定 manager 变量。

### CS005：禁止链式属性调用目标

若 Call.func 是 Attribute，且其直接 value 是 Attribute 或 Call，则拒绝：

```python
a.b.c()
a().b()
package.module.function()
```

模块路径没有通用例外，`await`、赋值上下文不豁免。仅装饰器声明表达式享有下文限定的豁免。应先绑定 owner：

```python
owner = package.module
result = owner.function()

owner = create()
owner.method()
```

`module.function()`、`obj.method()` 的 owner 是 Name，允许。规则准确限定上述 AST 形状，不泛化禁止所有属性、下标表达式；不过 call 结果的直接属性/下标消费仍会被 CS004 检出。

## 声明式例外（除装饰器外仅针对 CS004）

### 装饰器

函数、异步函数、类的整个 `decorator_list` 表达式子树视为框架声明，允许装饰器工厂以及任意嵌套工厂调用：

```python
@register(factory(config()))
def handle():
    pass
```

例外不扩散到函数体、参数默认值、注解或类基类。装饰器子树也豁免 CS005，以支持 `@pytest.mark.parametrize(...)` 等框架声明；CS001/CS002/CS003 仍正常检查，因此多行装饰器调用仍会失败。

### 函数默认值中的 dataclasses.field

仅对**整个默认值**恰为 `field(...)` 的情况放宽 CS004，适用于普通参数和仅关键字参数。检查器识别当前模块顶层的显式 `from dataclasses import field [as alias]`、`import dataclasses [as alias]`；不认可通配导入、其他模块的同名 field、局部/条件导入或任意 `.field()`。

```python
from dataclasses import field

def declaration(value=field(default_factory=list)):
    pass
```

例外仅针对这个外层 Call；`field(default=make())` 中的 `make()` 仍被拒绝，`[field()]` 也不算直接默认值。其他默认值工厂没有通用豁免，应先赋值到变量。数据类字段声明本身如 `items: list = field(default_factory=list)` 已属于 AnnAssign，无需例外。

### Annotated / type alias 元数据

显式从 `pydantic` 导入的 `Field` / `StringConstraints`（包括别名、`import pydantic as p`）作为 `typing.Annotated` / `typing_extensions.Annotated` 的直接元数据元素时，允许无需变量承接。Annotated 也必须由模块顶层显式导入识别。仅允许注解位置（参数、返回注解、AnnAssign）或 type alias 声明（PEP 695 `type Alias = ...`，以及赋值形式的别名）；支持外围的容器类型、联合类型。

```python
from typing import Annotated
from pydantic import Field, StringConstraints

type Positive = Annotated[int, Field(gt=0)]
type Name = Annotated[str, StringConstraints(min_length=1)]
```

仅豁免外层元数据 Call；`Field(default=make())` 仍拒绝内层 `make()`，传给普通函数的 `consume(Annotated[int, Field(...)])` 不是注解声明，也不豁免。非 Pydantic 的同名 Field 不豁免。

### 类配置与数据类字段

类体内 `model_config = ConfigDict(...)`、`items: list = field(default_factory=list)`、Pydantic 字段 `name: str = Field(...)` 原本就满足 Assign / AnnAssign，因此无须扩大豁免范围。`default_factory=list` 是函数引用而非函数调用；若写 `default_factory=make()`，内层调用仍必须先提取。

导入识别是有意限定的静态语法匹配，不解析动态导入、导入顺序、名称重绑定或作用域遮蔽；不要借用/覆盖声明模块别名来模拟豁免。所有例外仍受 CS003 单行参数约束，除装饰器外也受 CS005 链式调用规则约束。

## 测试范围

测试包含每条规则的正反例、同步/异步函数与上下文、await/yield、嵌套调用、装饰器与 field 例外边界、返回注解跨行、PEP 695、Unicode 列偏移、注释/字符串/续行、编码与读取错误、CLI 退出码/诊断、默认扫描范围、递归排除与去重，并检查工具及测试文件自身合规。测试片段作为字符串传给检查器，不受宿主测试文件的 AST 检查影响。
