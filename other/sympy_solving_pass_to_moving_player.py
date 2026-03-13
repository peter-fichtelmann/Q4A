import sympy as sp

v_b_x, v_b_y = sp.symbols('v_b_x v_b_y')
z = sp.symbols('z', positive=True)
s_b_x, s_b_y, s_p_x, s_p_y, v_p_x, v_p_y, v_b_value = sp.symbols('s_b_x s_b_y s_p_x s_p_y v_p_x v_p_y v_b_value', constant=True)
a_value = sp.symbols('a_value', constant=True)
# Your example system
a = (-a_value*v_b_x/v_b_value)
eq1 = 2 * (s_b_x - s_p_x) / a + 2 * (v_b_x - v_p_x) / a * z + z**2
eq2 = 2 * (s_b_y - s_p_y) / a + 2 * (v_b_y - v_p_y) / a * z + z**2
eq3 = sp.sqrt(v_b_x**2 + v_b_y**2) - v_b_value

solutions = sp.solve([eq1, eq2, eq3], (v_b_x, v_b_y, z))
print(solutions)