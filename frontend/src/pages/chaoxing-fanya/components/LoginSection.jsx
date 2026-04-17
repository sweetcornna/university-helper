import { CARD } from '../utils'


export default function LoginSection({ username, setUsername, password, setPassword, loginLoading, handleLogin }) {


  return (
    <section className={CARD}>


      <h2 className="mb-4 text-xl font-semibold text-slate-900">登录账号</h2>


      <form className="grid gap-4 md:grid-cols-2" onSubmit={handleLogin}>


        <input


          className="rounded-xl border border-slate-200 bg-white px-4 py-3"


          placeholder="请输入超星账号"


          value={username}


          onChange={(event) => setUsername(event.target.value)}


          required


        />


        <input


          className="rounded-xl border border-slate-200 bg-white px-4 py-3"


          type="password"


          placeholder="请输入密码"


          value={password}


          onChange={(event) => setPassword(event.target.value)}


          required


        />


        <button


          type="submit"


          disabled={loginLoading}


          className="min-h-[44px] cursor-pointer rounded-xl bg-sky-600 px-6 py-3 font-medium text-white transition duration-200 hover:bg-sky-500 disabled:cursor-not-allowed disabled:bg-slate-400"


        >


          {loginLoading ? '登录中...' : '登录并获取课程'}


        </button>


      </form>


    </section>
  )


}
