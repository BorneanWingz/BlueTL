with open('c:\\Users\\Blue-Wingz\\BlueTL\\app.py', 'r', encoding='utf-8') as f:
    content = f.read()

# Fix region_lines indentation
old = "def region_lines(self,text):\n  return [line.strip() for line in text.replace('\\\\r','').split('\\\\n') if line.strip()]"
new = "def region_lines(self,text):\n    return [line.strip() for line in text.replace('\\\\r','').split('\\\\n') if line.strip()]"

if old in content:
    content = content.replace(old, new)
    with open('c:\\Users\\Blue-Wingz\\BlueTL\\app.py', 'w', encoding='utf-8') as f:
        f.write(content)
    print("Fixed region_lines indentation")
else:
    print("Pattern not found")

# Also check and fix add method if needed
old2 = "  def add(self):\n  if not self.recognized:"
new2 = "  def add(self):\n    if not self.recognized:"
if old2 in content:
    content = content.replace(old2, new2)
    with open('c:\\Users\\Blue-Wingz\\BlueTL\\app.py', 'w', encoding='utf-8') as f:
        f.write(content)
    print("Fixed add indentation")
else:
    print("add pattern not found")