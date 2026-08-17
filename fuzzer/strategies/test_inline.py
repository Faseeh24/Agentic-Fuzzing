
from hypothesis import strategies as st

@st.composite
def xml_strategy(draw):
    name = draw(st.sampled_from(["a","b","c","root"]))
    if draw(st.booleans()):
        return f"<{name}/>"
    else:
        return f"<{name}>hello</{name}>"
