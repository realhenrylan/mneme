# 描述界面

---
title: 描述 UI
translators:
  - ChelesteWang
  - QC-L
  - KnowsCount
  - lyj505
---

<Intro>

React 是一个用于构建用户界面（UI）的 JavaScript 库，用户界面由按钮、文本和图像等小单元内容构建而成。React 帮助你把它们组合成可重用、可嵌套的 *组件*。从 web 端网站到移动端应用，屏幕上的所有内容都可以被分解成组件。在本章节中，你将学习如何创建、定制以及有条件地显示 React 组件。

</Intro>

<YouWillLearn isChapter={true}>

* [如何创建你的第一个组件](/learn/your-first-component)
* [在什么时候以及如何创建多文件组件](/learn/importing-and-exporting-components)
* [如何使用 JSX 为 JavaScript 添加标签](/learn/writing-markup-with-jsx)
* [如何在 JSX 中使用花括号来从组件中使用 JavaScript 功能](/learn/javascript-in-jsx-with-curly-braces)
* [如何用 props 配置组件](/learn/passing-props-to-a-component)
* [如何有条件地渲染组件](/learn/conditional-rendering)
* [如何在同一时间渲染多个组件](/learn/rendering-lists)
* [如何通过保持组件的纯粹性来避免令人困惑的错误](/learn/keeping-components-pure)
* [为什么将 UI 理解为树是有用的](/learn/understanding-your-ui-as-a-tree)

</YouWillLearn>

## 你的第一个组件 {/*your-first-component*/}

React 应用是由被称为 **组件** 的独立 UI 片段构建而成。React 组件本质上是可以任意添加标签的 JavaScript 函数。组件可以小到一个按钮，也可以大到是整个页面。这是一个 `Gallery` 组件，用于渲染三个 `Profile` 组件：

<Sandpack>

```js
function Profile() {
  return (
    <img
      src="https://react.dev/images/docs/scientists/MK3eW3As.jpg"
      alt="Katherine Johnson"
    />
  );
}

export default function Gallery() {
  return (
    <section>
      <h1>Amazing scientists</h1>
      <Profile />
      <Profile />
      <Profile />
    </section>
  );
}
```

```css
img { margin: 0 10px 10px 0; height: 90px; }
```

</Sandpack>

<LearnMore path="/learn/your-first-component">

请参阅 **[你的第一个组件](/learn/your-first-component)** 以学习如何声明并使用 React 组件

</LearnMore>

## 组件的导入与导出 {/*importing-and-exporting-components*/}

你可以在一个文件中声明许多组件，但文件的体积过大会变得难以浏览。为了解决这个问题，你可以在一个文件中只*导出*一个组件，然后再从另一个文件中*导入*该组件：

<Sandpack>

```js src/App.js hidden
import Gallery from './Gallery.js';

export default function App() {
  return (
    <Gallery />
  );
}
```

```js src/Gallery.js active
import Profile from './Profile.js';

export default function Gallery() {
  return (
    <section>
      <h1>Amazing scientists</h1>
      <Profile />
      <Profile />
      <Profile />
    </section>
  );
}
```

```js src/Profile.js
export default function Profile() {
  return (
    <img
      src="https://react.dev/images/docs/scientists/QIrZWGIs.jpg"
      alt="Alan L. Hart"
    />
  );
}
```

```css
img { margin: 0 10px 10px 0; }
```

</Sandpack>

<LearnMore path="/learn/importing-and-exporting-components">

请参阅 **[组件的导入与导出](/learn/importing-and-exporting-components)** 以学习如何切分组件。
</LearnMore>

## 使用 JSX 书写标签语言 {/*writing-markup-with-jsx*/}

每个 React 组件都是一个 JavaScript 函数，它可能包含一些标签，React 会将其渲染到浏览器中。React 组件使用一种叫做 JSX 的语法扩展来表示该标签。JSX 看起来很像 HTML，但它更为严格，可以显示动态信息。

如果我们把现有的 HTML 标签粘贴到 React 组件中，它并不一定能成功运行：

<Sandpack>

```js
export default function TodoList() {
  return (
    // This doesn't quite work!
    <h1>Hedy Lamarr's Todos</h1>
    <img
      src="https://react.dev/images/docs/scientists/yXOvdOSs.jpg"
      alt="Hedy Lamarr"
      class="photo"
    >
    <ul>
      <li>Invent new traffic lights
      <li>Rehearse a movie scene
      <li>Improve spectrum technology
    </ul>
  );
}
```

```css
img { height: 90px; }
```

</Sandpack>

如果你有像这样的现有的 HTML 片段，你可以使用它进行语法转换 [converter](https://transform.tools/html-to-jsx)：

<Sandpack>

```js
export default function TodoList() {
  return (
    <>
      <h1>Hedy Lamarr's Todos</h1>
      <img
        src="https://react.dev/images/docs/scientists/yXOvdOSs.jpg"
        alt="Hedy Lamarr"
        className="photo"
      />
      <ul>
        <li>Invent new traffic lights</li>
        <li>Rehearse a movie scene</li>
        <li>Improve spectrum technology</li>
      </ul>
    </>
  );
}
```

```css
img { height: 90px; }
```

</Sandpack>

<LearnMore path="/learn/writing-markup-with-jsx">

请参阅 **[使用 JSX 书写标签语言](/learn/writing-markup-with-jsx)** 以学习如何编写有效的 JSX。

</LearnMore>

## 在 JSX 中通过大括号使用 JavaScript {/*javascript-in-jsx-with-curly-braces*/}

JSX 可以让你在 JavaScript 文件中编写类似 HTML 的标签语法，使渲染逻辑和内容展示维护在同一个地方。有时你会想在标签中添加一点 JavaScript 逻辑或引用一个动态属性。在这种情况下，你可以在 JSX 中使用花括号来为 JavaScript "开辟通道"：

<Sandpack>

```js
const person = {
  name: 'Gregorio Y. Zara',
  theme: {
    backgroundColor: 'black',
    color: 'pink'
  }
};

export default function TodoList() {
  return (
    <div style={person.theme}>
      <h1>{person.name}'s Todos</h1>
      <img
        className="avatar"
        src="https://react.dev/images/docs/scientists/7vQD0fPs.jpg"
        alt="Gregorio Y. Zara"
      />
      <ul>
        <li>Improve the videophone</li>
        <li>Prepare aeronautics lectures</li>
        <li>Work on the alcohol-fuelled engine</li>
      </ul>
    </div>
  );
}
```

```css
body { padding: 0; margin: 0 }
body > div > div { padding: 20px; }
.avatar { border-radius: 50%; height: 90px; }
```

</Sandpack>

<LearnMore path="/learn/javascript-in-jsx-with-curly-braces">

请参阅 **[在 JSX 中通过大括号使用 JavaScript](/learn/javascript-in-jsx-with-curly-braces)** 以学习如何从 JSX 中访问 JavaScript 数据。

</LearnMore>

## 将 Props 传递给组件 {/*passing-props-to-a-component*/}

React 组件使用 *props* 来进行组件之间的通讯。每个父组件都可以通过为子组件提供 props 的方式来传递信息。props 可能会让你想起 HTML 属性，但你可以通过它们传递任何 JavaScript 的值，包括对象、数组、函数、甚至是 JSX!

<Sandpack>

```js
import { getImageUrl } from './utils.js'

export default function Profile() {
  return (
    <Card>
      <Avatar
        size={100}
        person={{
          name: 'Katsuko Saruhashi',
          imageId: 'YfeOqp2'
        }}
      />
    </Card>
  );
}

function Avatar({ person, size }) {
  return (
    <img
      className="avatar"
      src={getImageUrl(person)}
      alt={person.name}
      width={size}
      height={size}
    />
  );
}

function Card({ children }) {
  return (
    <div className="card">
      {children}
    </div>
  );
}

```

```js src/utils.js
export function getImageUrl(person, size = 's') {
  return (
    'https://react.dev/images/docs/scientists/' +
    person.imageId +
    size +
    '.jpg'
  );
}
```

```css
.card {
  width: fit-content;
  margin: 5px;
  padding: 5px;
  font-size: 20px;
  text-align: center;
  border: 1px solid #aaa;
  border-radius: 20px;
  background: #fff;
}
.avatar {
  margin: 20px;
  border-radius: 50%;
}
```

</Sandpack>

<LearnMore path="/learn/passing-props-to-a-component">

请参阅 **[将 Props 传递给组件](/learn/passing-props-to-a-component)** 以了解如何传递并读取 props。

</LearnMore>

## 条件渲染 {/*conditional-rendering*/}

你的组件经常需要根据不同的条件来显示不同的东西。在 React 中，你可以使用 JavaScript 语法，如 `if` 语句、`&&` 和 `? :` 操作符有条件地渲染 JSX。

在这个示例中，JavaScript 的 `&&` 操作符将会条件渲染一个复选标签：

<Sandpack>

```js
function Item({ name, isPacked }) {
  return (
    <li className="item">
      {name} {isPacked && '✅'}
    </li>
  );
}

export default function PackingList() {
  return (
    <section>
      <h1>Sally Ride's Packing List</h1>
      <ul>
        <Item
          isPacked={true}
          name="Space suit"
        />
        <Item
          isPacked={true}
          name="Helmet with a golden leaf"
        />
        <Item
          isPacked={false}
          name="Photo of Tam"
        />
      </ul>
    </section>
  );
}
```

</Sandpack>

<LearnMore path="/learn/conditional-rendering">

请参阅 **[条件渲染](/learn/conditional-rendering)** 以学习使用不同的方法对内容进行条件渲染。

</LearnMore>

## 渲染列表 {/*rendering-lists*/}

通常，你需要根据数据集合来渲染多个较为类似的组件。你可以在 React 中使用 JavaScript 的 `filter()` 和 `map()` 来实现数组的过滤和转换，将数据数组转换为组件数组。

对于数组的每个元素项，你需要指定一个 `key`。通常你需要使用数据库中的 ID 作为 `key`。即使列表发生了变化，React 也可以通过 key 来跟踪每个元素在列表中的位置。

<Sandpack>

```js src/App.js
import { people } from './data.js';
import { getImageUrl } from './utils.js';

export default function List() {
  const listItems = people.map(person =>
    <li key={person.id}>
      <img
        src={getImageUrl(person)}
        alt={person.name}
      />
      <p>
        <b>{person.name}:</b>
        {' ' + person.profession + ' '}
        known for {person.accomplishment}
      </p>
    </li>
  );
  return (
    <article>
      <h1>Scientists</h1>
      <ul>{listItems}</ul>
    </article>
  );
}
```

```js src/data.js
export const people = [{
  id: 0,
  name: 'Creola Katherine Johnson',
  profession: 'mathematician',
  accomplishment: 'spaceflight calculations',
  imageId: 'MK3eW3A'
}, {
  id: 1,
  name: 'Mario José Molina-Pasquel Henríquez',
  profession: 'chemist',
  accomplishment: 'discovery of Arctic ozone hole',
  imageId: 'mynHUSa'
}, {
  id: 2,
  name: 'Mohammad Abdus Salam',
  profession: 'physicist',
  accomplishment: 'electromagnetism theory',
  imageId: 'bE7W1ji'
}, {
  id: 3,
  name: 'Percy Lavon Julian',
  profession: 'chemist',
  accomplishment: 'pioneering cortisone drugs, steroids and birth control pills',
  imageId: 'IOjWm71'
}, {
  id: 4,
  name: 'Subrahmanyan Chandrasekhar',
  profession: 'astrophysicist',
  accomplishment: 'white dwarf star mass calculations',
  imageId: 'lrWQx8l'
}];
```

```js src/utils.js
export function getImageUrl(person) {
  return (
    'https://react.dev/images/docs/scientists/' +
    person.imageId +
    's.jpg'
  );
}
```

```css
ul { list-style-type: none; padding: 0px 10px; }
li {
  margin-bottom: 10px;
  display: grid;
  grid-template-columns: 1fr 1fr;
  align-items: center;
}
img { width: 100px; height: 100px; border-radius: 50%; }
h1 { font-size: 22px; }
h2 { font-size: 20px; }
```

</Sandpack>

<LearnMore path="/learn/rendering-lists">

请参阅 **[渲染列表](/learn/rendering-lists)** 以学习如何渲染一个组件列表，以及如何选择一个 `key`。

</LearnMore>

## 保持组件纯粹 {/*keeping-components-pure*/}

有些 JavaScript 函数是 **纯粹** 的。纯函数的基本定义：

* **只负责自己的任务**。 它不会更改在该函数调用前就已存在的对象或变量。
* **输入相同，输出也相同**。 在输入相同的情况下，对纯函数来说应总是返回相同的结果。

严格遵循纯函数的定义编写组件，可以让代码库体量增长时，避免一些令人困惑的错误和不可预测的行为。下面是一个非纯函数组件的示例：

<Sandpack>

```js {expectedErrors: {'react-compiler': [5]}}
let guest = 0;

function Cup() {
  // 不推荐的做法：直接修改一个已存在的变量。
  guest = guest + 1;
  return <h2>Tea cup for guest #{guest}</h2>;
}

export default function TeaSet() {
  return (
    <>
      <Cup />
      <Cup />
      <Cup />
    </>
  );
}
```

</Sandpack>

你可以通过传递一个 `props` 来使这个组件变得纯粹，而非修改已经存在的变量：

<Sandpack>

```js
function Cup({ guest }) {
  return <h2>Tea cup for guest #{guest}</h2>;
}

export default function TeaSet() {
  return (
    <>
      <Cup guest={1} />
      <Cup guest={2} />
      <Cup guest={3} />
    </>
  );
}
```

</Sandpack>

<LearnMore path="/learn/keeping-components-pure">

请参阅 **[保持组件纯粹](/learn/keeping-components-pure)** 以学习如何将组件写成纯粹且可预测的函数。

</LearnMore>

## 将 UI 视为树 {/*your-ui-as-a-tree*/}

React 使用树形关系建模以展示组件和模块之间的关系。

React 渲染树是组件之间父子关系的表示。

<Diagram name="generic_render_tree" height={250} width={500} alt="一个树状图，有五个节点，每个节点代表一个组件。树状图的顶部有一个名为 Root Component 的根节点，它有两个向下延伸的箭头，分别标有 renders。两个箭头指向标有 Component A 和 Component C 的节点。Component A 有一条 renders 箭头指向标有 Component B 的节点。Component C 有一条 renders 箭头指向标有 Component D 的节点。">

示例的 React 渲染树

</Diagram>

位于树顶部、靠近根组件的组件被视为顶层组件。没有子组件的组件被称为叶子组件。对组件的这种分类对于理解数据流和渲染性能非常有用。

对 JavaScript 模块之间的关系进行建模是了解应用程序的另一种有用方式。我们将其称为模块依赖树。

<Diagram name="generic_dependency_tree" height={250} width={500} alt="一个树状图，有五个节点。每个节点代表一个 JavaScript 模块。最顶部的节点标有 RootModule.js。它有三条箭头指向节点：ModuleA.js、ModuleB.js 和 ModuleC.js。每个箭头标有 imports。ModuleC.js 节点有一条 imports 箭头指向标有 ModuleD.js的节点。">

示例的模块依赖树

</Diagram>

构建工具经常使用依赖树来捆绑客户端下载和渲染所需的所有 JavaScript 代码。对于 React 应用程序，打包大小会导致用户体验退化。了解模块依赖树有助于调试此类问题。

<LearnMore path="/learn/understanding-your-ui-as-a-tree">

阅读 **[将 UI 视为树](/learn/understanding-your-ui-as-a-tree)** 以了解如何为 React 应用程序创建渲染和模块依赖树，以及它们如何成为有效改善用户体验和性能的心理模型。

</LearnMore>


## 接下来应该…… {/*whats-next*/}

请访问 [你的第一个组件](/learn/your-first-component) 这个章节并开始阅读！

如若你已熟悉这些主题，可直接阅读 [添加交互](/learn/adding-interactivity) 一节。

# 添加交互

---
title: 添加交互
---

<Intro>

界面上的控件会根据用户的输入而更新。例如，点击按钮切换轮播图的展示。在 React 中，随时间变化的数据被称为状态（state）。你可以向任何组件添加状态，并按需进行更新。在本章节中，你将学习如何编写处理交互的组件，更新它们的状态，并根据时间变化显示不同的效果。

</Intro>

<YouWillLearn isChapter={true}>

* [如何处理用户发起的事件](/learn/responding-to-events)
* [如何用状态使组件“记住”信息](/learn/state-a-components-memory)
* [React 是如何分两个阶段更新 UI 的](/learn/render-and-commit)
* [为什么状态在你改变后没有立即更新](/learn/state-as-a-snapshot)
* [如何排队进行多个状态的更新](/learn/queueing-a-series-of-state-updates)
* [如何更新状态中的对象](/learn/updating-objects-in-state)
* [如何更新状态中的数组](/learn/updating-arrays-in-state)

</YouWillLearn>

## 响应事件 {/*responding-to-events*/}

React 允许你向 JSX 中添加事件处理程序。事件处理程序是你自己的函数，它将在用户交互时被触发，如点击、悬停、焦点在表单输入框上等等。

`<button>` 等内置组件只支持内置浏览器事件，如 `onClick`。但是，你也可以创建你自己的组件，并给它们的事件处理程序 props 指定你喜欢的任何特定于应用的名称。

<Sandpack>

```js
export default function App() {
  return (
    <Toolbar
      onPlayMovie={() => alert('Playing!')}
      onUploadImage={() => alert('Uploading!')}
    />
  );
}

function Toolbar({ onPlayMovie, onUploadImage }) {
  return (
    <div>
      <Button onClick={onPlayMovie}>
        Play Movie
      </Button>
      <Button onClick={onUploadImage}>
        Upload Image
      </Button>
    </div>
  );
}

function Button({ onClick, children }) {
  return (
    <button onClick={onClick}>
      {children}
    </button>
  );
}
```

```css
button { margin-right: 10px; }
```

</Sandpack>

<LearnMore path="/learn/responding-to-events">

阅读 **[响应事件](/learn/responding-to-events)** 了解如何添加事件处理程序。

</LearnMore>

## State: 组件的记忆 {/*state-a-components-memory*/}

组件通常需要根据交互改变屏幕上的内容。在表单中键入更新输入栏，在轮播图上点击“下一个”改变显示的图片，点击“购买”将产品放入购物车。组件需要“记住”一些东西：当前的输入值、当前的图片、购物车。在 React 中，这种特定于组件的记忆被称为状态。

你可以用 [`useState`](/reference/react/useState) Hook 为组件添加状态。*Hook* 是能让你的组件使用 React 功能的特殊函数（状态是这些功能之一）。`useState` Hook 让你声明一个状态变量。它接收初始状态并返回一对值：当前状态，以及一个让你更新状态的设置函数。

```js
const [index, setIndex] = useState(0);
const [showMore, setShowMore] = useState(false);
```

下面是一个图库，演示如何使用并在点击时更新状态：

<Sandpack>

```js
import { useState } from 'react';
import { sculptureList } from './data.js';

export default function Gallery() {
  const [index, setIndex] = useState(0);
  const [showMore, setShowMore] = useState(false);
  const hasNext = index < sculptureList.length - 1;

  function handleNextClick() {
    if (hasNext) {
      setIndex(index + 1);
    } else {
      setIndex(0);
    }
  }

  function handleMoreClick() {
    setShowMore(!showMore);
  }

  let sculpture = sculptureList[index];
  return (
    <>
      <button onClick={handleNextClick}>
        Next
      </button>
      <h2>
        <i>{sculpture.name} </i>
        by {sculpture.artist}
      </h2>
      <h3>
        ({index + 1} of {sculptureList.length})
      </h3>
      <button onClick={handleMoreClick}>
        {showMore ? 'Hide' : 'Show'} details
      </button>
      {showMore && <p>{sculpture.description}</p>}
      <img
        src={sculpture.url}
        alt={sculpture.alt}
      />
    </>
  );
}
```

```js src/data.js
export const sculptureList = [{
  name: 'Homenaje a la Neurocirugía',
  artist: 'Marta Colvin Andrade',
  description: '尽管 Colvin 以暗示前西班牙符号的抽象主题而闻名，但这座巨大的雕塑是对神经外科的致敬，是她最知名的公共艺术作品之一。',
  url: 'https://react.dev/images/docs/scientists/Mx7dA2Y.jpg',
  alt: '一尊双手交叉的青铜雕像，它的手指优雅地握住一个人类的大脑。'
}, {
  name: 'Floralis Genérica',
  artist: 'Eduardo Catalano',
  description: '这朵巨大的银花（75 英尺或 23 米）位于布宜诺斯艾利斯。它并非静止的艺术，它能在晚上或强风吹拂时关闭花瓣，在早晨打开它们。',
  url: 'https://react.dev/images/docs/scientists/ZF6s192m.jpg',
  alt: '一个巨大的金属花卉雕塑，具有棱镜状的花瓣和坚固的雄蕊。'
}, {
  name: 'Eternal Presence',
  artist: 'John Woodrow Wilson',
  description: '威尔逊以专注于平等、社会正义以及人类的基本和精神品质而闻名。这个巨大的（7 英尺或 2.13 米）青铜代表了他所描述的“一种象征性的黑人存在，注入了“普遍的人性意识”。',
  url: 'https://react.dev/images/docs/scientists/aTtVpES.jpg',
  alt: '描绘人的头部的雕塑似乎从古至今都是庄严肃穆的。它们散发着平静和宁静。'
}, {
  name: 'Moai',
  artist: 'Unknown Artist',
  description: '在复活节岛上，有 1000 个石像，或现存的纪念碑雕像，由早期的拉帕努伊人创造，一些人认为代表神化的祖先。',
  url: 'https://react.dev/images/docs/scientists/RCwLEoQm.jpg',
  alt: 'Three monumental stone busts with the heads that are disproportionately large with somber faces.'
}, {
  name: 'Blue Nana',
  artist: 'Niki de Saint Phalle',
  description: 'Nana 是一群自信奔放的人，也是女性气质和母性的象征。最初，Saint Phalle 使用布料和废弃物品来创作 Nana，后来又引入合成树脂以实现更具活力的效果。',
  url: 'https://react.dev/images/docs/scientists/Sd1AgUOm.jpg',
  alt: '这是一件大型马赛克雕塑，展现了一个穿着绚丽服装、欢快舞蹈的女性形象，充满了喜悦和活力。'
}, {
  name: 'Ultimate Form',
  artist: 'Barbara Hepworth',
  description: '这座抽象的青铜雕塑是位于约克郡雕塑公园的《人类家族》系列的一部分。Hepworth 选择的不是创造世界的文字表现，而是受到人和景观的启发而发展出抽象的形式。',
  url: 'https://react.dev/images/docs/scientists/2heNQDcm.jpg',
  alt: 'A tall sculpture made of three elements stacked on each other reminding of a human figure.'
}, {
  name: 'Cavaliere',
  artist: 'Lamidi Olonade Fakeye',
  description: "法基是四代木雕家的后代，他的作品融合了传统和当代约鲁巴主题。",
  url: 'https://react.dev/images/docs/scientists/wIdGuZwm.png',
  alt: '一个复杂的木制战士雕塑，马背上有一张严肃的脸，脸上装饰着图案。'
}, {
  name: 'Big Bellies',
  artist: 'Alina Szapocznikow',
  description: "Szapocznikow 以她的肢体破损的雕塑而闻名，这些雕塑隐喻了年轻和美丽的脆弱和短暂。这座雕塑描绘了两个非常逼真的大肚皮，彼此叠放在一起，每个大约5英尺（1.5米）高。",
  url: 'https://react.dev/images/docs/scientists/AlHTAdDm.jpg',
  alt: '这座雕塑让人联想到层叠的褶皱，与古典雕塑中的腹部截然不同。'
}, {
  name: 'Terracotta Army',
  artist: 'Unknown Artist',
  description: '兵马俑是一组陶俑雕塑，描绘了中国第一个皇帝秦始皇的军队。军队由8000多名士兵、130辆战车、520匹马和150匹骑兵组成。',
  url: 'https://react.dev/images/docs/scientists/HMFmH6m.jpg',
  alt: '12 个庄严的武士兵马俑，每个都有独特的面部表情和盔甲。'
}, {
  name: 'Lunar Landscape',
  artist: 'Louise Nevelson',
  description: 'Nevelson 以从纽约市的废墟中捡拾物体而闻名，后来她将这些碎片组装成纪念性建筑。在这幅画中，她使用了不同的部分，如床柱、杂耍的大头针和座椅碎片，将它们钉在盒子里并粘在一起，反映了立体主义对空间和形式的几何抽象的影响。',
  url: 'https://react.dev/images/docs/scientists/rN7hY6om.jpg',
  alt: '一种黑色哑光雕塑，其中单个元素最初无法区分。'
}, {
  name: 'Aureole',
  artist: 'Ranjani Shettar',
  description: 'Shettar 融合了传统与现代、自然与工业。她的艺术关注人与自然的关系。她的工作被描述为在抽象和比喻上都引人注目，挑战重力，以及“不太可能的材料的精细合成”。"',
  url: 'https://react.dev/images/docs/scientists/okTpbHhm.jpg',
  alt: '一个苍白的线状雕塑安装在混凝土墙上，并下降到地板上。它看起来很轻。'
}, {
  name: 'Hippos',
  artist: '台北动物园',
  description: '台北动物园委托建造了河马广场，以水下河马为特色。',
  url: 'https://react.dev/images/docs/scientists/6o5Vuyu.jpg',
  alt: '一组青铜河马雕塑从露台的人行道上出现，好像他们在游泳。'
}];
```

```css
h2 { margin-top: 10px; margin-bottom: 0; }
h3 {
 margin-top: 5px;
 font-weight: normal;
 font-size: 100%;
}
img { width: 120px; height: 120px; }
button {
  display: block;
  margin-top: 10px;
  margin-bottom: 10px;
}
```

</Sandpack>

<LearnMore path="/learn/state-a-components-memory">

阅读 **[State: 组件的记忆](/learn/state-a-components-memory)** 了解如何记住一个值并在交互时更新它。

</LearnMore>

## 渲染和提交 {/*render-and-commit*/}

在你的组件显示在屏幕上之前，它们必须由 React 进行渲染。理解这个过程中的步骤有助于你思考你的代码如何执行并解释其行为。

想象一下，你的组件是厨房里的厨师，用食材制作出美味的菜肴。在这个场景中，React 是服务员，负责提出顾客的要求，并给顾客上菜。这个请求和服务 UI 的过程有三个步骤：

1. **触发**渲染（将食客的订单送到厨房）
2. **渲染**组件（在厨房准备订单）
3. **提交**到 DOM（将订单送到桌前）

<IllustrationBlock sequential>
  <Illustration caption="Trigger" alt="React 就像一个餐厅的服务员，从用户那里获取订单，并将它们送到组件厨房。" src="/images/docs/illustrations/i_render-and-commit1.png" />
  <Illustration caption="Render" alt="Card 厨师给 React 提供了一个新鲜的 Card 组件。" src="/images/docs/illustrations/i_render-and-commit2.png" />
  <Illustration caption="Commit" alt="React 将 Card 送到用户桌前。" src="/images/docs/illustrations/i_render-and-commit3.png" />
</IllustrationBlock>

<LearnMore path="/learn/render-and-commit">

阅读 **[渲染和提交](/learn/render-and-commit)** 了解 UI 更新的生命周期。

</LearnMore>

## state 如同一张快照 {/*state-as-a-snapshot*/}

与普通 JavaScript 变量不同，React 状态的行为更像一个快照。设置它并不改变你已有的状态变量，而是触发一次重新渲染。这在一开始可能会让人感到惊讶！

```js
console.log(count);  // 0
setCount(count + 1); // 请求用 1 重新渲染
console.log(count);  // 仍然是 0！
```

React 这样工作是为了帮助你避免微妙的 bug。这里有一个小的聊天应用程序。试着猜一猜，如果先按下“发送”，然后再把收件人改为 Bob，会发生什么？五秒钟后，谁的名字会出现在 `alert` 中？

<Sandpack>

```js
import { useState } from 'react';

export default function Form() {
  const [to, setTo] = useState('Alice');
  const [message, setMessage] = useState('Hello');

  function handleSubmit(e) {
    e.preventDefault();
    setTimeout(() => {
      alert(`You said ${message} to ${to}`);
    }, 5000);
  }

  return (
    <form onSubmit={handleSubmit}>
      <label>
        To:{' '}
        <select
          value={to}
          onChange={e => setTo(e.target.value)}>
          <option value="Alice">Alice</option>
          <option value="Bob">Bob</option>
        </select>
      </label>
      <textarea
        placeholder="Message"
        value={message}
        onChange={e => setMessage(e.target.value)}
      />
      <button type="submit">Send</button>
    </form>
  );
}
```

```css
label, textarea { margin-bottom: 10px; display: block; }
```

</Sandpack>


<LearnMore path="/learn/state-as-a-snapshot">

阅读 **[state 如同一张快照](/learn/state-as-a-snapshot)** 了解为什么状态在事件处理程序中是“固定的”和不变的。

</LearnMore>

## 把一系列 state 更新加入队列 {/*queueing-a-series-of-state-updates*/}

这个组件有问题：点击“+3”只能增加一次分数。

<Sandpack>

```js
import { useState } from 'react';

export default function Counter() {
  const [score, setScore] = useState(0);

  function increment() {
    setScore(score + 1);
  }

  return (
    <>
      <button onClick={() => increment()}>+1</button>
      <button onClick={() => {
        increment();
        increment();
        increment();
      }}>+3</button>
      <h1>Score: {score}</h1>
    </>
  )
}
```

```css
button { display: inline-block; margin: 10px; font-size: 20px; }
```

</Sandpack>

[state 如同一张快照](/learn/state-as-a-snapshot) 解释了为什么会出现这种情况。设置状态会请求一个新的重新渲染，但不会在已运行的代码中更改它。所以在你调用 `setScore(score + 1)` 后，`score` 仍然是 `0`。

```js
console.log(score);  // 0
setScore(score + 1); // setScore(0 + 1);
console.log(score);  // 0
setScore(score + 1); // setScore(0 + 1);
console.log(score);  // 0
setScore(score + 1); // setScore(0 + 1);
console.log(score);  // 0
```

你可以通过在设置状态时传递一个 *更新器函数* 来解决这个问题。注意用 `setScore(s => s + 1)` 替换 `setScore(score + 1)` 是如何修复“+3”按钮的。如果你需要排队进行多次状态更新，那么这非常方便。

<Sandpack>

```js
import { useState } from 'react';

export default function Counter() {
  const [score, setScore] = useState(0);

  function increment() {
    setScore(s => s + 1);
  }

  return (
    <>
      <button onClick={() => increment()}>+1</button>
      <button onClick={() => {
        increment();
        increment();
        increment();
      }}>+3</button>
      <h1>Score: {score}</h1>
    </>
  )
}
```

```css
button { display: inline-block; margin: 10px; font-size: 20px; }
```

</Sandpack>

<LearnMore path="/learn/queueing-a-series-of-state-updates">

阅读 **[把一系列 state 更新加入队列](/learn/queueing-a-series-of-state-updates)** 了解如何在下一次渲染前排队多个更新。

</LearnMore>

## 更新 state 中的对象 {/*updating-objects-in-state*/}

状态可以持有任何类型的 JavaScript 值，包括对象。但你不应该直接改变你在 React 状态中持有的对象和数组。相反，当你想更新一个对象和数组时，你需要创建一个新的对象（或复制现有的对象），然后用这个副本来更新状态。

通常情况下，你会使用 `...` 展开语法来复制你想改变的对象和数组。例如，更新一个嵌套对象可以是这样的：

<Sandpack>

```js
import { useState } from 'react';

export default function Form() {
  const [person, setPerson] = useState({
    name: 'Niki de Saint Phalle',
    artwork: {
      title: 'Blue Nana',
      city: 'Hamburg',
      image: 'https://react.dev/images/docs/scientists/Sd1AgUOm.jpg',
    }
  });

  function handleNameChange(e) {
    setPerson({
      ...person,
      name: e.target.value
    });
  }

  function handleTitleChange(e) {
    setPerson({
      ...person,
      artwork: {
        ...person.artwork,
        title: e.target.value
      }
    });
  }

  function handleCityChange(e) {
    setPerson({
      ...person,
      artwork: {
        ...person.artwork,
        city: e.target.value
      }
    });
  }

  function handleImageChange(e) {
    setPerson({
      ...person,
      artwork: {
        ...person.artwork,
        image: e.target.value
      }
    });
  }

  return (
    <>
      <label>
        Name:
        <input
          value={person.name}
          onChange={handleNameChange}
        />
      </label>
      <label>
        Title:
        <input
          value={person.artwork.title}
          onChange={handleTitleChange}
        />
      </label>
      <label>
        City:
        <input
          value={person.artwork.city}
          onChange={handleCityChange}
        />
      </label>
      <label>
        Image:
        <input
          value={person.artwork.image}
          onChange={handleImageChange}
        />
      </label>
      <p>
        <i>{person.artwork.title}</i>
        {' by '}
        {person.name}
        <br />
        (located in {person.artwork.city})
      </p>
      <img
        src={person.artwork.image}
        alt={person.artwork.title}
      />
    </>
  );
}
```

```css
label { display: block; }
input { margin-left: 5px; margin-bottom: 5px; }
img { width: 200px; height: 200px; }
```

</Sandpack>

如果在代码中复制对象感觉乏味，可以使用 [Immer](https://github.com/immerjs/use-immer) 之类的库来减少重复代码：

<Sandpack>

```js
import { useImmer } from 'use-immer';

export default function Form() {
  const [person, updatePerson] = useImmer({
    name: 'Niki de Saint Phalle',
    artwork: {
      title: 'Blue Nana',
      city: 'Hamburg',
      image: 'https://react.dev/images/docs/scientists/Sd1AgUOm.jpg',
    }
  });

  function handleNameChange(e) {
    updatePerson(draft => {
      draft.name = e.target.value;
    });
  }

  function handleTitleChange(e) {
    updatePerson(draft => {
      draft.artwork.title = e.target.value;
    });
  }

  function handleCityChange(e) {
    updatePerson(draft => {
      draft.artwork.city = e.target.value;
    });
  }

  function handleImageChange(e) {
    updatePerson(draft => {
      draft.artwork.image = e.target.value;
    });
  }

  return (
    <>
      <label>
        Name:
        <input
          value={person.name}
          onChange={handleNameChange}
        />
      </label>
      <label>
        Title:
        <input
          value={person.artwork.title}
          onChange={handleTitleChange}
        />
      </label>
      <label>
        City:
        <input
          value={person.artwork.city}
          onChange={handleCityChange}
        />
      </label>
      <label>
        Image:
        <input
          value={person.artwork.image}
          onChange={handleImageChange}
        />
      </label>
      <p>
        <i>{person.artwork.title}</i>
        {' by '}
        {person.name}
        <br />
        (located in {person.artwork.city})
      </p>
      <img
        src={person.artwork.image}
        alt={person.artwork.title}
      />
    </>
  );
}
```

```json package.json
{
  "dependencies": {
    "immer": "1.7.3",
    "react": "latest",
    "react-dom": "latest",
    "react-scripts": "latest",
    "use-immer": "0.5.1"
  },
  "scripts": {
    "start": "react-scripts start",
    "build": "react-scripts build",
    "test": "react-scripts test --env=jsdom",
    "eject": "react-scripts eject"
  }
}
```

```css
label { display: block; }
input { margin-left: 5px; margin-bottom: 5px; }
img { width: 200px; height: 200px; }
```

</Sandpack>

<LearnMore path="/learn/updating-objects-in-state">

阅读 **[更新 state 中的对象](/learn/updating-objects-in-state)** 了解如何正确地更新对象。

</LearnMore>

## 更新 state 中的数组 {/*updating-arrays-in-state*/}

数组是另一种可以存在状态中的可变 JavaScript 对象，应将其视为只读。就像对象一样，当你想更新存在状态中的数组时，你需要创建一个新数组（或者复制现有数组），然后用新数组来更新状态。

<Sandpack>

```js
import { useState } from 'react';

const initialList = [
  { id: 0, title: 'Big Bellies', seen: false },
  { id: 1, title: 'Lunar Landscape', seen: false },
  { id: 2, title: 'Terracotta Army', seen: true },
];

export default function BucketList() {
  const [list, setList] = useState(
    initialList
  );

  function handleToggle(artworkId, nextSeen) {
    setList(list.map(artwork => {
      if (artwork.id === artworkId) {
        return { ...artwork, seen: nextSeen };
      } else {
        return artwork;
      }
    }));
  }

  return (
    <>
      <h1>Art Bucket List</h1>
      <h2>My list of art to see:</h2>
      <ItemList
        artworks={list}
        onToggle={handleToggle} />
    </>
  );
}

function ItemList({ artworks, onToggle }) {
  return (
    <ul>
      {artworks.map(artwork => (
        <li key={artwork.id}>
          <label>
            <input
              type="checkbox"
              checked={artwork.seen}
              onChange={e => {
                onToggle(
                  artwork.id,
                  e.target.checked
                );
              }}
            />
            {artwork.title}
          </label>
        </li>
      ))}
    </ul>
  );
}
```

</Sandpack>

如果在代码中复制数组感觉乏味，可以使用 [Immer](https://github.com/immerjs/use-immer) 之类的库来减少重复代码：

<Sandpack>

```js
import { useState } from 'react';
import { useImmer } from 'use-immer';

const initialList = [
  { id: 0, title: 'Big Bellies', seen: false },
  { id: 1, title: 'Lunar Landscape', seen: false },
  { id: 2, title: 'Terracotta Army', seen: true },
];

export default function BucketList() {
  const [list, updateList] = useImmer(initialList);

  function handleToggle(artworkId, nextSeen) {
    updateList(draft => {
      const artwork = draft.find(a =>
        a.id === artworkId
      );
      artwork.seen = nextSeen;
    });
  }

  return (
    <>
      <h1>Art Bucket List</h1>
      <h2>My list of art to see:</h2>
      <ItemList
        artworks={list}
        onToggle={handleToggle} />
    </>
  );
}

function ItemList({ artworks, onToggle }) {
  return (
    <ul>
      {artworks.map(artwork => (
        <li key={artwork.id}>
          <label>
            <input
              type="checkbox"
              checked={artwork.seen}
              onChange={e => {
                onToggle(
                  artwork.id,
                  e.target.checked
                );
              }}
            />
            {artwork.title}
          </label>
        </li>
      ))}
    </ul>
  );
}
```

```json package.json
{
  "dependencies": {
    "immer": "1.7.3",
    "react": "latest",
    "react-dom": "latest",
    "react-scripts": "latest",
    "use-immer": "0.5.1"
  },
  "scripts": {
    "start": "react-scripts start",
    "build": "react-scripts build",
    "test": "react-scripts test --env=jsdom",
    "eject": "react-scripts eject"
  }
}
```

</Sandpack>

<LearnMore path="/learn/updating-arrays-in-state">

阅读 **[更新 state 中的数组](/learn/updating-arrays-in-state)** 了解如何正确地更新数组。

</LearnMore>

## 下节预告 {/*whats-next*/}

前往 [响应事件](/learn/responding-to-events) 开始逐页阅读本章！

或者，如果你已经熟悉这些主题，不妨看看 [状态管理](/learn/managing-state)

# 管理状态

---
title: 状态管理
translators:
  - qinhua
  - KnowsCount
  - QC-L
---

<Intro>

随着你的应用不断变大，更有意识的去关注应用状态如何组织，以及数据如何在组件之间流动会对你很有帮助。冗余或重复的状态往往是缺陷的根源。在本节中，你将学习如何组织好状态，如何保持状态更新逻辑的可维护性，以及如何跨组件共享状态。

</Intro>

<YouWillLearn isChapter={true}>

* [如何将 UI 变更视为状态变更](/learn/reacting-to-input-with-state)
* [如何组织好状态](/learn/choosing-the-state-structure)
* [如何使用“状态提升”在组件之间共享状态](/learn/sharing-state-between-components)
* [如何控制状态的保留或重置](/learn/preserving-and-resetting-state)
* [如何在函数中整合复杂的状态逻辑](/learn/extracting-state-logic-into-a-reducer)
* [如何避免数据通过 prop 逐级透传](/learn/passing-data-deeply-with-context)
* [如何随着应用的增长去扩展状态管理](/learn/scaling-up-with-reducer-and-context)

</YouWillLearn>

## 用 State 响应输入 {/*reacting-to-input-with-state*/}

使用 React，你不用直接从代码层面修改 UI。例如，不用编写诸如“禁用按钮”、“启用按钮”、“显示成功消息”等命令。相反，你只需要描述组件在不同状态（“初始状态”、“输入状态”、“成功状态”）下希望展现的 UI，然后根据用户输入触发状态更改。这和设计师对 UI 的理解很相似。

下面是一个使用 React 编写的反馈表单。请注意看它是如何使用 `status` 这个状态变量来决定启用或禁用提交按钮，以及是否显示成功消息的。

<Sandpack>

```js
import { useState } from 'react';

export default function Form() {
  const [answer, setAnswer] = useState('');
  const [error, setError] = useState(null);
  const [status, setStatus] = useState('typing');

  if (status === 'success') {
    return <h1>答对了！</h1>
  }

  async function handleSubmit(e) {
    e.preventDefault();
    setStatus('submitting');
    try {
      await submitForm(answer);
      setStatus('success');
    } catch (err) {
      setStatus('typing');
      setError(err);
    }
  }

  function handleTextareaChange(e) {
    setAnswer(e.target.value);
  }

  return (
    <>
      <h2>城市测验</h2>
      <p>
        哪个城市有把空气变成饮用水的广告牌？
      </p>
      <form onSubmit={handleSubmit}>
        <textarea
          value={answer}
          onChange={handleTextareaChange}
          disabled={status === 'submitting'}
        />
        <br />
        <button disabled={
          answer.length === 0 ||
          status === 'submitting'
        }>
          提交
        </button>
        {error !== null &&
          <p className="Error">
            {error.message}
          </p>
        }
      </form>
    </>
  );
}

function submitForm(answer) {
  // 模拟接口请求
  return new Promise((resolve, reject) => {
    setTimeout(() => {
      let shouldError = answer.toLowerCase() !== 'lima'
      if (shouldError) {
        reject(new Error('猜的不错，但答案不对。再试试看吧！'));
      } else {
        resolve();
      }
    }, 1500);
  });
}
```

```css
.Error { color: red; }
```

</Sandpack>

<LearnMore path="/learn/reacting-to-input-with-state">

阅读 **[用 State 响应输入](/learn/reacting-to-input-with-state)** 来学习如何以状态驱动的思维处理交互。

</LearnMore>

## 选择 State 结构 {/*choosing-the-state-structure*/}

良好的状态组织，可以区分开易于修改和调试的组件与频繁出问题的组件。最重要的原则是，状态不应包含冗余或重复的信息。如果包含一些多余的状态，我们会很容易忘记去更新它，从而导致问题产生！

例如，这个表单有一个多余的 `fullName` 状态变量：

<Sandpack>

```js
import { useState } from 'react';

export default function Form() {
  const [firstName, setFirstName] = useState('');
  const [lastName, setLastName] = useState('');
  const [fullName, setFullName] = useState('');

  function handleFirstNameChange(e) {
    setFirstName(e.target.value);
    setFullName(e.target.value + ' ' + lastName);
  }

  function handleLastNameChange(e) {
    setLastName(e.target.value);
    setFullName(firstName + ' ' + e.target.value);
  }

  return (
    <>
      <h2>让我们帮你登记</h2>
      <label>
        名：{' '}
        <input
          value={firstName}
          onChange={handleFirstNameChange}
        />
      </label>
      <label>
        姓：{' '}
        <input
          value={lastName}
          onChange={handleLastNameChange}
        />
      </label>
      <p>
        你的票据将签发给：<b>{fullName}</b>
      </p>
    </>
  );
}
```

```css
label { display: block; margin-bottom: 5px; }
```

</Sandpack>

你可以移除它并在组件渲染时通过计算 `fullName` 来简化代码：

<Sandpack>

```js
import { useState } from 'react';

export default function Form() {
  const [firstName, setFirstName] = useState('');
  const [lastName, setLastName] = useState('');

  const fullName = firstName + ' ' + lastName;

  function handleFirstNameChange(e) {
    setFirstName(e.target.value);
  }

  function handleLastNameChange(e) {
    setLastName(e.target.value);
  }

  return (
    <>
      <h2>让我们帮你登记</h2>
      <label>
        名：{' '}
        <input
          value={firstName}
          onChange={handleFirstNameChange}
        />
      </label>
      <label>
        姓：{' '}
        <input
          value={lastName}
          onChange={handleLastNameChange}
        />
      </label>
      <p>
        你的票将发给：<b>{fullName}</b>
      </p>
    </>
  );
}
```

```css
label { display: block; margin-bottom: 5px; }
```

</Sandpack>

这看起来似乎只是一个小改动，但却可以避免很多潜在的问题。
<LearnMore path="/learn/choosing-the-state-structure">

阅读 **[选择 State 结构](/learn/choosing-the-state-structure)** 来学习如何组织状态并避开错误。

</LearnMore>

## 在组件间共享状态 {/*sharing-state-between-components*/}

有时候你希望两个组件的状态始终同步更改。要实现这一点，可以将相关状态从这两个组件上移除，并把这些状态移到最近的父级组件，然后通过 props 将状态传递给这两个组件。这被称为“状态提升”，这是编写 React 代码时常做的事。

在以下示例中，要求每次只能激活一个面板。要实现这一点，父组件将管理激活状态并为其子组件指定 prop，而不是将激活状态保留在各自的子组件中。

<Sandpack>

```js
import { useState } from 'react';

export default function Accordion() {
  const [activeIndex, setActiveIndex] = useState(0);
  return (
    <>
      <h2>Almaty, Kazakhstan</h2>
      <Panel
        title="关于"
        isActive={activeIndex === 0}
        onShow={() => setActiveIndex(0)}
      >
        阿拉木图人口约200万，是哈萨克斯坦最大的城市。在1929年至1997年之间，它是该国首都。
      </Panel>
      <Panel
        title="词源"
        isActive={activeIndex === 1}
        onShow={() => setActiveIndex(1)}
      >
        这个名字源于哈萨克语 <span lang="kk-KZ">алма</span>，是“苹果”的意思，通常被翻译成“满是苹果”。事实上，阿拉木图周围的地区被认为是苹果的祖籍，<i lang="la">Malus sieversii</i> 被认为是目前本土苹果的祖先。
      </Panel>
    </>
  );
}

function Panel({
  title,
  children,
  isActive,
  onShow
}) {
  return (
    <section className="panel">
      <h3>{title}</h3>
      {isActive ? (
        <p>{children}</p>
      ) : (
        <button onClick={onShow}>
          显示
        </button>
      )}
    </section>
  );
}
```

```css
h3, p { margin: 5px 0px; }
.panel {
  padding: 10px;
  border: 1px solid #aaa;
}
```

</Sandpack>

<LearnMore path="/learn/sharing-state-between-components">

阅读 **[在组件间共享状态](/learn/sharing-state-between-components)** 来学习如何提升状态并保持组件同步。

</LearnMore>

## 对 State 进行保留和重置 {/*preserving-and-resetting-state*/}

当你重新渲染一个组件时， React 需要决定组件树中的哪些部分要保留和更新，以及丢弃或重新创建。在大多数情况下， React 的自动处理机制已经做得足够好了。默认情况下，React 会保留树中与先前渲染的组件树“匹配”的部分。

然而，有时这并不是你想要的。例如，在下面这个程序中，输入内容后再切换收件人并不会清空输入框。这可能会导致用户不小心发错消息：

<Sandpack>

```js src/App.js
import { useState } from 'react';
import Chat from './Chat.js';
import ContactList from './ContactList.js';

export default function Messenger() {
  const [to, setTo] = useState(contacts[0]);
  return (
    <div>
      <ContactList
        contacts={contacts}
        selectedContact={to}
        onSelect={contact => setTo(contact)}
      />
      <Chat contact={to} />
    </div>
  )
}

const contacts = [
  { name: 'Taylor', email: 'taylor@mail.com' },
  { name: 'Alice', email: 'alice@mail.com' },
  { name: 'Bob', email: 'bob@mail.com' }
];
```

```js src/ContactList.js
export default function ContactList({
  selectedContact,
  contacts,
  onSelect
}) {
  return (
    <section className="contact-list">
      <ul>
        {contacts.map(contact =>
          <li key={contact.email}>
            <button onClick={() => {
              onSelect(contact);
            }}>
              {contact.name}
            </button>
          </li>
        )}
      </ul>
    </section>
  );
}
```

```js src/Chat.js
import { useState } from 'react';

export default function Chat({ contact }) {
  const [text, setText] = useState('');
  return (
    <section className="chat">
      <textarea
        value={text}
        placeholder={'Chat to ' + contact.name}
        onChange={e => setText(e.target.value)}
      />
      <br />
      <button>发送给 {contact.email}</button>
    </section>
  );
}
```

```css
.chat, .contact-list {
  float: left;
  margin-bottom: 20px;
}
ul, li {
  list-style: none;
  margin: 0;
  padding: 0;
}
li button {
  width: 100px;
  padding: 10px;
  margin-right: 10px;
}
textarea {
  height: 150px;
}
```

</Sandpack>

React 允许你覆盖默认行为，可通过向组件传递一个唯一 `key`（如 `<Chat key={email}/>` 来 *强制* 重置其状态。这会告诉 React ，如果收件人不同，应将其作为一个 **不同的** `Chat` 组件，需要使用新数据和 UI（比如输入框）来重新创建它。现在，在接收者之间切换时就会重置输入框——即使渲染的是同一个组件。

<Sandpack>

```js src/App.js
import { useState } from 'react';
import Chat from './Chat.js';
import ContactList from './ContactList.js';

export default function Messenger() {
  const [to, setTo] = useState(contacts[0]);
  return (
    <div>
      <ContactList
        contacts={contacts}
        selectedContact={to}
        onSelect={contact => setTo(contact)}
      />
      <Chat key={to.email} contact={to} />
    </div>
  )
}

const contacts = [
  { name: 'Taylor', email: 'taylor@mail.com' },
  { name: 'Alice', email: 'alice@mail.com' },
  { name: 'Bob', email: 'bob@mail.com' }
];
```

```js src/ContactList.js
export default function ContactList({
  selectedContact,
  contacts,
  onSelect
}) {
  return (
    <section className="contact-list">
      <ul>
        {contacts.map(contact =>
          <li key={contact.email}>
            <button onClick={() => {
              onSelect(contact);
            }}>
              {contact.name}
            </button>
          </li>
        )}
      </ul>
    </section>
  );
}
```

```js src/Chat.js
import { useState } from 'react';

export default function Chat({ contact }) {
  const [text, setText] = useState('');
  return (
    <section className="chat">
      <textarea
        value={text}
        placeholder={'Chat to ' + contact.name}
        onChange={e => setText(e.target.value)}
      />
      <br />
      <button>发送给 {contact.email}</button>
    </section>
  );
}
```

```css
.chat, .contact-list {
  float: left;
  margin-bottom: 20px;
}
ul, li {
  list-style: none;
  margin: 0;
  padding: 0;
}
li button {
  width: 100px;
  padding: 10px;
  margin-right: 10px;
}
textarea {
  height: 150px;
}
```

</Sandpack>

<LearnMore path="/learn/preserving-and-resetting-state">

阅读 **[对 State 进行保留和重置](/learn/preserving-and-resetting-state)** 来学习状态的生命周期以及如何控制它。

</LearnMore>

## 迁移状态逻辑至 Reducer 中 {/*extracting-state-logic-into-a-reducer*/}

对于那些需要更新多个状态的组件来说，过于分散的事件处理程序可能会令人不知所措。对于这种情况，你可以在组件外部将所有状态更新逻辑合并到一个称为 “reducer” 的函数中。这样，事件处理程序就会变得简洁，因为它们只需要指定用户的 “actions”。在文件的底部，reducer 函数指定状态应该如何更新以响应每个 action！

<Sandpack>

```js src/App.js
import { useReducer } from 'react';
import AddTask from './AddTask.js';
import TaskList from './TaskList.js';

export default function TaskApp() {
  const [tasks, dispatch] = useReducer(
    tasksReducer,
    initialTasks
  );

  function handleAddTask(text) {
    dispatch({
      type: 'added',
      id: nextId++,
      text: text,
    });
  }

  function handleChangeTask(task) {
    dispatch({
      type: 'changed',
      task: task
    });
  }

  function handleDeleteTask(taskId) {
    dispatch({
      type: 'deleted',
      id: taskId
    });
  }

  return (
    <>
      <h1>布拉格行程</h1>
      <AddTask
        onAddTask={handleAddTask}
      />
      <TaskList
        tasks={tasks}
        onChangeTask={handleChangeTask}
        onDeleteTask={handleDeleteTask}
      />
    </>
  );
}

function tasksReducer(tasks, action) {
  switch (action.type) {
    case 'added': {
      return [...tasks, {
        id: action.id,
        text: action.text,
        done: false
      }];
    }
    case 'changed': {
      return tasks.map(t => {
        if (t.id === action.task.id) {
          return action.task;
        } else {
          return t;
        }
      });
    }
    case 'deleted': {
      return tasks.filter(t => t.id !== action.id);
    }
    default: {
      throw Error('未知操作：' + action.type);
    }
  }
}

let nextId = 3;
const initialTasks = [
  { id: 0, text: '参观卡夫卡博物馆', done: true },
  { id: 1, text: '看木偶戏', done: false },
  { id: 2, text: '列侬墙图片', done: false }
];
```

```js src/AddTask.js hidden
import { useState } from 'react';

export default function AddTask({ onAddTask }) {
  const [text, setText] = useState('');
  return (
    <>
      <input
        placeholder="添加任务"
        value={text}
        onChange={e => setText(e.target.value)}
      />
      <button onClick={() => {
        setText('');
        onAddTask(text);
      }}>添加</button>
    </>
  )
}
```

```js src/TaskList.js hidden
import { useState } from 'react';

export default function TaskList({
  tasks,
  onChangeTask,
  onDeleteTask
  }) {
  return (
    <ul>
      {tasks.map(task => (
        <li key={task.id}>
          <Task
            task={task}
            onChange={onChangeTask}
            onDelete={onDeleteTask}
          />
        </li>
      ))}
    </ul>
  );
}

function Task({ task, onChange, onDelete }) {
  const [isEditing, setIsEditing] = useState(false);
  let taskContent;
  if (isEditing) {
    taskContent = (
      <>
        <input
          value={task.text}
          onChange={e => {
            onChange({
              ...task,
              text: e.target.value
            });
          }} />
        <button onClick={() => setIsEditing(false)}>
          保存
        </button>
      </>
    );
  } else {
    taskContent = (
      <>
        {task.text}
        <button onClick={() => setIsEditing(true)}>
          编辑
        </button>
      </>
    );
  }
  return (
    <label>
      <input
        type="checkbox"
        checked={task.done}
        onChange={e => {
          onChange({
            ...task,
            done: e.target.checked
          });
        }}
      />
      {taskContent}
      <button onClick={() => onDelete(task.id)}>
        删除
      </button>
    </label>
  );
}
```

```css
button { margin: 5px; }
li { list-style-type: none; }
ul, li { margin: 0; padding: 0; }
```

</Sandpack>

<LearnMore path="/learn/extracting-state-logic-into-a-reducer">

阅读 **[迁移状态逻辑至 Reducer 中](/learn/extracting-state-logic-into-a-reducer)** 来学习如何在 reducer 函数中整合逻辑。

</LearnMore>

## 使用 Context 深层传递参数 {/*passing-data-deeply-with-context*/}

通常，你会通过 props 将信息从父组件传递给子组件。但是，如果要在组件树中深入传递一些 prop，或者树里的许多组件需要使用相同的 prop，那么传递 prop 可能会变得很麻烦。Context 允许父组件将一些信息提供给它下层的任何组件，不管该组件多深层也无需通过 props 逐层透传。

这里的 `Heading` 组件通过“询问”最近的 `Section` 来确定其标题级别。每个 `Section` 的级别是通过给父 `Section` 添加的级别来确定的。每个 `Section` 都向它下层的所有组件提供信息，不需要逐层传递 props，而是通过 Context 来实现。

<Sandpack>

```js
import Heading from './Heading.js';
import Section from './Section.js';

export default function Page() {
  return (
    <Section>
      <Heading>大标题</Heading>
      <Section>
        <Heading>一级标题</Heading>
        <Heading>一级标题</Heading>
        <Heading>一级标题</Heading>
        <Section>
          <Heading>二级标题</Heading>
          <Heading>二级标题</Heading>
          <Heading>二级标题</Heading>
          <Section>
            <Heading>三级标题</Heading>
            <Heading>三级标题</Heading>
            <Heading>三级标题</Heading>
          </Section>
        </Section>
      </Section>
    </Section>
  );
}
```

```js src/Section.js
import { useContext } from 'react';
import { LevelContext } from './LevelContext.js';

export default function Section({ children }) {
  const level = useContext(LevelContext);
  return (
    <section className="section">
      <LevelContext value={level + 1}>
        {children}
      </LevelContext>
    </section>
  );
}
```

```js src/Heading.js
import { useContext } from 'react';
import { LevelContext } from './LevelContext.js';

export default function Heading({ children }) {
  const level = useContext(LevelContext);
  switch (level) {
    case 0:
      throw Error('标题必须在 Section 内！');
    case 1:
      return <h1>{children}</h1>;
    case 2:
      return <h2>{children}</h2>;
    case 3:
      return <h3>{children}</h3>;
    case 4:
      return <h4>{children}</h4>;
    case 5:
      return <h5>{children}</h5>;
    case 6:
      return <h6>{children}</h6>;
    default:
      throw Error('未知级别：' + level);
  }
}
```

```js src/LevelContext.js
import { createContext } from 'react';

export const LevelContext = createContext(0);
```

```css
.section {
  padding: 10px;
  margin: 5px;
  border-radius: 5px;
  border: 1px solid #aaa;
}
```

</Sandpack>

<LearnMore path="/learn/passing-data-deeply-with-context">

阅读 **[使用 Context 深层传递参数](/learn/passing-data-deeply-with-context)** 来学习如何使用 Context 来代替传递 props。

</LearnMore>

## 使用 Reducer 和 Context 拓展你的应用 {/*scaling-up-with-reducer-and-context*/}

Reducer 帮助你合并组件的状态更新逻辑。Context 帮助你将信息深入传递给其他组件。你可以将 reducers 和 context 组合在一起使用，以管理复杂应用的状态。

基于这种想法，使用 reducer 来管理一个具有复杂状态的父组件。组件树中任何深度的其他组件都可以通过 context 读取其状态。还可以 dispatch 一些 action 来更新状态。

<Sandpack>

```js src/App.js
import AddTask from './AddTask.js';
import TaskList from './TaskList.js';
import { TasksProvider } from './TasksContext.js';

export default function TaskApp() {
  return (
    <TasksProvider>
      <h1>在京都休息一天</h1>
      <AddTask />
      <TaskList />
    </TasksProvider>
  );
}
```

```js src/TasksContext.js
import { createContext, useContext, useReducer } from 'react';

const TasksContext = createContext(null);
const TasksDispatchContext = createContext(null);

export function TasksProvider({ children }) {
  const [tasks, dispatch] = useReducer(
    tasksReducer,
    initialTasks
  );

  return (
    <TasksContext value={tasks}>
      <TasksDispatchContext value={dispatch}>
        {children}
      </TasksDispatchContext>
    </TasksContext>
  );
}

export function useTasks() {
  return useContext(TasksContext);
}

export function useTasksDispatch() {
  return useContext(TasksDispatchContext);
}

function tasksReducer(tasks, action) {
  switch (action.type) {
    case 'added': {
      return [...tasks, {
        id: action.id,
        text: action.text,
        done: false
      }];
    }
    case 'changed': {
      return tasks.map(t => {
        if (t.id === action.task.id) {
          return action.task;
        } else {
          return t;
        }
      });
    }
    case 'deleted': {
      return tasks.filter(t => t.id !== action.id);
    }
    default: {
      throw Error('未知操作：' + action.type);
    }
  }
}

const initialTasks = [
  { id: 0, text: '哲学家之路', done: true },
  { id: 1, text: '参观寺庙', done: false },
  { id: 2, text: '喝抹茶', done: false }
];
```

```js src/AddTask.js
import { useState, useContext } from 'react';
import { useTasksDispatch } from './TasksContext.js';

export default function AddTask({ onAddTask }) {
  const [text, setText] = useState('');
  const dispatch = useTasksDispatch();
  return (
    <>
      <input
        placeholder="添加任务"
        value={text}
        onChange={e => setText(e.target.value)}
      />
      <button onClick={() => {
        setText('');
        dispatch({
          type: 'added',
          id: nextId++,
          text: text,
        });
      }}>添加</button>
    </>
  );
}

let nextId = 3;
```

```js src/TaskList.js
import { useState, useContext } from 'react';
import { useTasks, useTasksDispatch } from './TasksContext.js';

export default function TaskList() {
  const tasks = useTasks();
  return (
    <ul>
      {tasks.map(task => (
        <li key={task.id}>
          <Task task={task} />
        </li>
      ))}
    </ul>
  );
}

function Task({ task }) {
  const [isEditing, setIsEditing] = useState(false);
  const dispatch = useTasksDispatch();
  let taskContent;
  if (isEditing) {
    taskContent = (
      <>
        <input
          value={task.text}
          onChange={e => {
            dispatch({
              type: 'changed',
              task: {
                ...task,
                text: e.target.value
              }
            });
          }} />
        <button onClick={() => setIsEditing(false)}>
          保存
        </button>
      </>
    );
  } else {
    taskContent = (
      <>
        {task.text}
        <button onClick={() => setIsEditing(true)}>
          编辑
        </button>
      </>
    );
  }
  return (
    <label>
      <input
        type="checkbox"
        checked={task.done}
        onChange={e => {
          dispatch({
            type: 'changed',
            task: {
              ...task,
              done: e.target.checked
            }
          });
        }}
      />
      {taskContent}
      <button onClick={() => {
        dispatch({
          type: 'deleted',
          id: task.id
        });
      }}>
        删除
      </button>
    </label>
  );
}
```

```css
button { margin: 5px; }
li { list-style-type: none; }
ul, li { margin: 0; padding: 0; }
```

</Sandpack>


<LearnMore path="/learn/scaling-up-with-reducer-and-context">

阅读 **[使用 Reducer 和 Context 拓展你的应用](/learn/scaling-up-with-reducer-and-context)** 来学习如何在不断增长的应用程序中扩展状态管理。

</LearnMore>

## 下节预告 {/*whats-next*/}

跳转到 [用 State 响应输入](/learn/reacting-to-input-with-state) 这一节并开始一页页的阅读！

当然，如果你已经熟悉了这些内容，可以去读一读 [脱围机制](/learn/escape-hatches)?
