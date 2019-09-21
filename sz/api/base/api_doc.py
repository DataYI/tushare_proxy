import inspect
import traceback
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from functools import update_wrapper
from typing import List, Callable

from flask import request, Response
from werkzeug.routing import Rule

from sz import application
from sz.application import logger
from sz.api.base.errors import ApiError
from sz.api.base.reply_base import json_response, ReplyBase
import colorama


def web_api(func):
    """
    json_api 装饰器, 它应该处于 flask route 装饰器的下面, 并且应该是控制器方法上最近的一个包装器
    :param func: 被装饰器所包装的函数方法
    :return: 返回包装后的函数方法
    """

    def wrapper(*args, **kwds):
        return_json = False
        try:
            # func_map = JsonApiViewFunctionsSpec()
            arg_spec = inspect.getfullargspec(func)
            # func_map.put(full_name_of_func(func), arg_spec)
            for arg_index, arg_name in enumerate(arg_spec.args):
                load_arg_from_request(arg_name, arg_index, kwds, arg_spec)

            reply = func(*args, **kwds)

            if isinstance(reply, ReplyBase):
                return_json = True
                return json_response(reply)
            elif isinstance(reply, Response):
                reply.headers['Access-Control-Allow-Origin'] = '*'
                return reply
            elif isinstance(reply, str):
                response = Response(reply, content_type = 'text/plain; charset=utf-8')
                response.headers['Access-Control-Allow-Origin'] = '*'
                return response

        except ApiError as e:
            reply = ReplyBase()
            reply.ret = e.err_code
            reply.err_msg = e.err_msg
            reply.traceback = traceback.format_exc()
            return json_response(reply)
        except BaseException as e:
            if return_json:
                reply = ReplyBase()
                reply.ret = -1
                reply.err_msg = str(e)
                reply.traceback = traceback.format_exc()
                return json_response(reply)
            else:
                # logger.debug(colorama.Fore.RED + '=================================')

                logger().error(colorama.Fore.RED + traceback.format_exc())
                raise e

    wrapper.__original__fun__ = func

    return update_wrapper(wrapper, func)


def load_arg_from_request(arg_name: str, arg_index: int, arg_map: dict, arg_spec: inspect.FullArgSpec):
    try:
        arg_v: str = request.values.get(arg_name, None)
        if arg_v is None and not_default_arg(arg_index, arg_spec):
            raise ApiError(err_msg = 'missing required parameter: %s' % arg_name)
        elif arg_v is not None:
            arg_type = type_of_arg(arg_name, arg_spec)
            if arg_type == str:
                arg_map[arg_name] = arg_v
            elif arg_type == int:
                arg_map[arg_name] = int(arg_v)
            elif arg_type == float:
                arg_map[arg_name] = float(arg_v)
            elif arg_type == bool:
                arg_map[arg_name] = arg_v.upper() == 'TRUE'
            elif arg_type == datetime:
                arg_map[arg_name] = datetime.strptime(arg_v, '%Y-%m-%d %H:%M:%S')
            elif arg_type == Decimal:
                arg_map[arg_name] = Decimal(arg_v)
            else:
                raise ApiError('parameter type must be one of: str, int, float, bool, datetime, Decimal.')
    except ApiError as ex:
        raise ex
    except Exception as ex:
        raise ApiError(str(ex))


def not_default_arg(arg_index: int, arg_spec: inspect.FullArgSpec) -> bool:
    offset = length(arg_spec.args) - length(arg_spec.defaults)
    return arg_index - offset < 0


def length(length_able) -> int:
    if length_able is None:
        return 0
    else:
        return len(length_able)


def type_of_arg(arg_name: str, arg_spec: inspect.FullArgSpec) -> type:
    return arg_spec.annotations[arg_name]


def full_name_of_func(func) -> str:
    return '%s.%s' % (func.__module__, func.__qualname__)


@dataclass
class WebApiArg:
    # 参数名称
    name: str = ''
    # 参数位置索引
    index: int = 0
    # 参数是否具有默认值
    has_default: bool = False
    # 参数的默认值
    default: str = ''
    # 参数的类型描述
    type_desc: str = '开发人员很懒,没有标注参数的类型,鄙视他吧👎'


@dataclass
class WebApiFunc:
    path: str = ''
    func_module_name: str = None
    func_qualified_name: str = None
    func_full_name: str = None
    comments: str = ''
    doc: str = '开发人员很懒,没有留下文档说明,鄙视他吧👎'
    has_doc: bool = False
    brief: str = ''  # first line of doc
    support_get: bool = False
    support_post: bool = False
    args: List[WebApiArg] = None
    return_json: bool = True

    def load(self, rule: Rule):
        self.path = rule.rule
        func = application.app.view_functions[rule.endpoint]
        self.func_module_name = func.__module__
        self.func_qualified_name = func.__qualname__
        self.func_full_name = full_name_of_func(func)
        self.comments = inspect.getcomments(func)
        self.return_json = is_json_api_func(func)

        fun_doc = inspect.getdoc(func)
        if fun_doc:
            self.doc = fun_doc
            self.has_doc = True

        self.brief = self.doc.splitlines()[0]

        self.support_get = 'GET' in rule.methods
        self.support_post = 'POST' in rule.methods
        self.args = list()

        if hasattr(func, '__original__fun__'):
            arg_spec = inspect.getfullargspec(func.__original__fun__)
        else:
            arg_spec = inspect.getfullargspec(func)
        offset = WebApiFunc.length(arg_spec.args) - WebApiFunc.length(arg_spec.defaults)
        for arg_index, arg_name in enumerate(arg_spec.args):
            if arg_name == 'self':
                continue

            arg = WebApiArg()
            arg.name = arg_name
            arg.index = arg_index
            arg.has_default = arg_index - offset >= 0
            arg.type_desc = arg_spec.annotations[arg_name].__name__

            if arg.has_default:
                default_v = arg_spec.defaults[arg_index - offset]
                arg_type = arg_spec.annotations[arg_name]
                if arg_type == str:
                    arg.default = '"%s"' % default_v
                elif arg_type == datetime:
                    arg.default = default_v.strftime('%Y-%m-%d %H:%M:%S')
                else:
                    arg.default = str(default_v)

            self.args.append(arg)

        return self

    @staticmethod
    def length(arg_list: List) -> int:
        if arg_list is None:
            return 0
        else:
            return len(arg_list)


def is_json_api_func(func: Callable) -> bool:
    """
    判断是否是标注为 api 接口的 rule, 并且返回的是 json (ReplyBase)
    """

    if hasattr(func, '__original__fun__'):
        return_cls = inspect.getfullargspec(func.__original__fun__).annotations.get('return', None)
        if return_cls is None:
            return False
        else:
            return issubclass(return_cls, ReplyBase)
    else:
        return False


def is_web_api_func(rule: Rule) -> bool:
    func = application.app.view_functions[rule.endpoint]
    return hasattr(func, '__original__fun__')


def all_web_api() -> List[WebApiFunc]:
    rules = filter(is_web_api_func, application.app.url_map.iter_rules())
    return [WebApiFunc().load(rule) for rule in rules]
