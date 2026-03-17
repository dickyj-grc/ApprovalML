"""
Expression evaluator for ApprovalML conditional logic and template variables.
Safely evaluates expressions within approval workflow contexts.
"""

import ast
import operator
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional


class ExpressionError(Exception):
    """Raised when expression evaluation fails"""
    pass


@dataclass
class EvaluationContext:
    """Context for expression evaluation with form data and workflow variables"""
    form_data: Dict[str, Any]
    workflow_variables: Dict[str, Any]
    requestor: Dict[str, Any]
    system: Dict[str, Any]
    current_step: Optional[str] = None
    execution_id: Optional[int] = None


class TemplateVariableResolver:
    """Resolves template variables like ${requestor.supervisor} and ${form.amount}"""

    def __init__(self, context: EvaluationContext):
        self.context = context

    def resolve_variable(self, variable_path: str) -> Any:
        """Resolve a variable path like 'requestor.supervisor' or 'form.amount'"""
        parts = variable_path.split('.')

        if len(parts) < 2:
            raise ExpressionError(f"Invalid variable path: {variable_path}")

        root = parts[0]
        path = parts[1:]

        # Get root context
        if root == 'requestor':
            current = self.context.requestor
        elif root == 'form':
            current = self.context.form_data
        elif root == 'workflow':
            current = self.context.workflow_variables
        elif root == 'system':
            current = self.context.system
        else:
            raise ExpressionError(f"Unknown variable root: {root}")

        # Navigate path
        for part in path:
            if isinstance(current, dict):
                if part not in current:
                    raise ExpressionError(f"Variable path not found: {variable_path}")
                current = current[part]
            else:
                # Handle object attributes if needed
                if hasattr(current, part):
                    current = getattr(current, part)
                else:
                    raise ExpressionError(f"Variable path not found: {variable_path}")

        return current

    def resolve_template(self, template: str) -> str:
        """Resolve all template variables in a string"""
        variable_pattern = r'\$\{([^}]+)\}'

        def replace_variable(match):
            variable_path = match.group(1)
            try:
                value = self.resolve_variable(variable_path)
                return str(value)
            except ExpressionError:
                return match.group(0)  # Return original if can't resolve

        return re.sub(variable_pattern, replace_variable, template)


class SafeExpressionEvaluator:
    """Safely evaluates conditional expressions with restricted operations"""

    # Allowed operators for security
    ALLOWED_OPERATORS = {
        ast.Eq: operator.eq,
        ast.NotEq: operator.ne,
        ast.Lt: operator.lt,
        ast.LtE: operator.le,
        ast.Gt: operator.gt,
        ast.GtE: operator.ge,
        ast.In: lambda x, y: x in y,
        ast.NotIn: lambda x, y: x not in y,
        ast.And: lambda x, y: x and y,
        ast.Or: lambda x, y: x or y,
        ast.Not: operator.not_,
        ast.Add: operator.add,
        ast.Sub: operator.sub,
        ast.Mult: operator.mul,
        ast.Div: operator.truediv,
        ast.Mod: operator.mod,
    }

    ALLOWED_FUNCTIONS = {
        'len': len,
        'str': str,
        'int': int,
        'float': float,
        'bool': bool,
        'abs': abs,
        'min': min,
        'max': max,
        'sum': sum,
        'round': round,
    }

    def __init__(self, context: EvaluationContext):
        self.context = context
        self.resolver = TemplateVariableResolver(context)

    def evaluate_condition(self, field: str, operator_str: str, value: Any) -> bool:
        """Evaluate a single condition like 'amount > 1000'"""
        try:
            # Get field value from context
            if field in self.context.form_data:
                field_value = self.context.form_data[field]
            elif field in self.context.workflow_variables:
                field_value = self.context.workflow_variables[field]
            else:
                raise ExpressionError(f"Field '{field}' not found in context")

            # Evaluate based on operator
            if operator_str == '==':
                return field_value == value
            elif operator_str == '!=':
                return field_value != value
            elif operator_str == '>':
                return field_value > value
            elif operator_str == '<':
                return field_value < value
            elif operator_str == '>=':
                return field_value >= value
            elif operator_str == '<=':
                return field_value <= value
            elif operator_str == 'in':
                return field_value in value
            elif operator_str == 'not_in':
                return field_value not in value
            elif operator_str == 'contains':
                return value in str(field_value)
            elif operator_str == 'not_contains':
                return value not in str(field_value)
            else:
                raise ExpressionError(f"Unknown operator: {operator_str}")

        except (TypeError, ValueError) as e:
            raise ExpressionError(f"Error evaluating condition: {str(e)}")

    def evaluate_expression(self, expression: str) -> Any:
        """Safely evaluate a Python expression with restricted operations"""
        try:
            # First resolve any template variables
            resolved_expression = self.resolver.resolve_template(expression)

            # Parse the expression
            tree = ast.parse(resolved_expression, mode='eval')

            # Evaluate with restricted operations
            return self._eval_node(tree.body)

        except SyntaxError as e:
            raise ExpressionError(f"Invalid expression syntax: {str(e)}")
        except Exception as e:
            raise ExpressionError(f"Error evaluating expression: {str(e)}")

    def _eval_node(self, node: ast.AST) -> Any:
        """Recursively evaluate AST nodes with security restrictions"""
        if isinstance(node, ast.Constant):
            return node.value
        elif isinstance(node, ast.Num):  # Python < 3.8 compatibility
            return node.n
        elif isinstance(node, ast.Str):  # Python < 3.8 compatibility
            return node.s
        elif isinstance(node, ast.Name):
            # Allow access to context variables
            if node.id in self.context.form_data:
                return self.context.form_data[node.id]
            elif node.id in self.context.workflow_variables:
                return self.context.workflow_variables[node.id]
            elif node.id in self.ALLOWED_FUNCTIONS:
                return self.ALLOWED_FUNCTIONS[node.id]
            else:
                raise ExpressionError(f"Unknown variable: {node.id}")
        elif isinstance(node, ast.BinOp):
            left = self._eval_node(node.left)
            right = self._eval_node(node.right)
            op_type = type(node.op)
            if op_type in self.ALLOWED_OPERATORS:
                return self.ALLOWED_OPERATORS[op_type](left, right)
            else:
                raise ExpressionError(f"Operator not allowed: {op_type.__name__}")
        elif isinstance(node, ast.Compare):
            left = self._eval_node(node.left)
            for op, comparator in zip(node.ops, node.comparators):
                right = self._eval_node(comparator)
                op_type = type(op)
                if op_type in self.ALLOWED_OPERATORS:
                    if not self.ALLOWED_OPERATORS[op_type](left, right):
                        return False
                    left = right
                else:
                    raise ExpressionError(f"Comparison operator not allowed: {op_type.__name__}")
            return True
        elif isinstance(node, ast.BoolOp):
            op_type = type(node.op)
            if op_type == ast.And:
                return all(self._eval_node(value) for value in node.values)
            elif op_type == ast.Or:
                return any(self._eval_node(value) for value in node.values)
            else:
                raise ExpressionError(f"Boolean operator not allowed: {op_type.__name__}")
        elif isinstance(node, ast.UnaryOp):
            operand = self._eval_node(node.operand)
            op_type = type(node.op)
            if op_type in self.ALLOWED_OPERATORS:
                return self.ALLOWED_OPERATORS[op_type](operand)
            else:
                raise ExpressionError(f"Unary operator not allowed: {op_type.__name__}")
        elif isinstance(node, ast.Call):
            func_name = node.func.id if isinstance(node.func, ast.Name) else None
            if func_name in self.ALLOWED_FUNCTIONS:
                args = [self._eval_node(arg) for arg in node.args]
                return self.ALLOWED_FUNCTIONS[func_name](*args)
            else:
                raise ExpressionError(f"Function not allowed: {func_name}")
        elif isinstance(node, ast.List):
            return [self._eval_node(item) for item in node.elts]
        elif isinstance(node, ast.Tuple):
            return tuple(self._eval_node(item) for item in node.elts)
        elif isinstance(node, ast.Dict):
            return {
                self._eval_node(k): self._eval_node(v)
                for k, v in zip(node.keys, node.values)
            }
        else:
            raise ExpressionError(f"AST node type not allowed: {type(node).__name__}")


class TimeoutParser:
    """Parses timeout strings like '48_hours' or '5_business_days'"""

    @staticmethod
    def parse_timeout(timeout_str: str) -> timedelta:
        """Parse timeout string and return timedelta"""
        pattern = r'^(\d+)_(hours|business_days|days|minutes)$'
        match = re.match(pattern, timeout_str)

        if not match:
            raise ExpressionError(f"Invalid timeout format: {timeout_str}")

        amount = int(match.group(1))
        unit = match.group(2)

        if unit == 'minutes':
            return timedelta(minutes=amount)
        elif unit == 'hours':
            return timedelta(hours=amount)
        elif unit == 'days':
            return timedelta(days=amount)
        elif unit == 'business_days':
            # Approximate business days as days * 1.4 (accounting for weekends)
            return timedelta(days=amount * 1.4)
        else:
            raise ExpressionError(f"Unknown time unit: {unit}")

    @staticmethod
    def calculate_due_date(timeout_str: str, start_time: datetime = None) -> datetime:
        """Calculate due date from timeout string"""
        if start_time is None:
            start_time = datetime.now(timezone.utc)

        timeout_delta = TimeoutParser.parse_timeout(timeout_str)
        return start_time + timeout_delta


class ConditionEvaluator:
    """Evaluates workflow conditions"""

    def __init__(self, context: EvaluationContext):
        self.context = context

    def evaluate_conditions(
        self, conditions: list, logic: str = "AND"
    ) -> bool:
        """Evaluate a list of conditions"""
        if not conditions:
            return True

        results = []
        for cond in conditions:
            field_value = self.context.form_data.get(cond.field)
            if field_value is None:
                results.append(False)
                continue

            op = cond.operator
            val = cond.value

            if op == '==':
                results.append(field_value == val)
            elif op == '!=':
                results.append(field_value != val)
            elif op == '>':
                results.append(field_value > val)
            elif op == '<':
                results.append(field_value < val)
            elif op == '>=':
                results.append(field_value >= val)
            elif op == '<=':
                results.append(field_value <= val)
            else:
                results.append(False)

        if logic.upper() == "AND":
            return all(results)
        elif logic.upper() == "OR":
            return any(results)
        return False


# Utility functions
def create_evaluation_context(
    form_data: Dict[str, Any],
    requestor_data: Dict[str, Any],
    workflow_variables: Optional[Dict[str, Any]] = None,
    execution_id: Optional[int] = None
) -> EvaluationContext:
    """Create evaluation context from workflow execution data"""
    return EvaluationContext(
        form_data=form_data,
        workflow_variables=workflow_variables or {},
        requestor=requestor_data,
        system={
            'current_time': datetime.now(timezone.utc),
            'execution_id': execution_id,
        },
        execution_id=execution_id
    )


def evaluate_template_string(template: str, context: EvaluationContext) -> str:
    """Convenience function to evaluate template string"""
    resolver = TemplateVariableResolver(context)
    return resolver.resolve_template(template)
