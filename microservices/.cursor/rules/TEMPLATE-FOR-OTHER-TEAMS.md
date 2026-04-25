# Template for Other Teams - Chessverse Cursor Rules

## 🎯 How to Add Cursor Rules to Your Service

### Step 1: Copy the Structure
```bash
# Copy the entire .cursor/rules/ directory to your service
cp -r .cursor/rules/ /path/to/your/service/
```

### Step 2: Customize for Your Stack

#### For Node.js Services:
Update `20-stack-best-practices.mdc`:
```markdown
### Node.js + Express/Nest
- Use TypeScript interfaces for all data structures
- Express: Router pattern with middleware
- Nest: Decorators and dependency injection
- Jest for testing with ≥ 80% coverage
- ESLint + Prettier for code quality
```

#### For React Frontend:
Update `20-stack-best-practices.mdc`:
```markdown
### React + TypeScript
- Functional components with hooks
- Custom hooks for logic reuse
- Vitest + Testing Library for testing
- ≥ 70% coverage requirement
- Component composition over inheritance
```

#### For Vue Frontend:
Update `20-stack-best-practices.mdc`:
```markdown
### Vue + TypeScript
- Composition API with <script setup>
- TypeScript interfaces for props
- Vitest for testing
- ≥ 70% coverage requirement
- Single File Components (SFC)
```

### Step 3: Update Project Context
Edit `00-project-overview.mdc`:
```markdown
### Technology Stack
**Current Service**: Node.js + Express + MongoDB
**Other Services**: Python + FastAPI, React + TypeScript, etc.
```

### Step 4: Test the Rules
```bash
# In your service directory
@Cursor Rules
```

## 📋 Checklist for New Services

- [ ] Copied `.cursor/rules/` structure
- [ ] Updated `00-project-overview.mdc` with your stack
- [ ] Customized `20-stack-best-practices.mdc` for your technology
- [ ] Tested with `@Cursor Rules` command
- [ ] Added mention in your service README
- [ ] Notified team about the new rules

## 🔧 Technology-Specific Examples

### Python + FastAPI (Current)
```python
# Already configured - see existing files
```

### Node.js + Express
```typescript
// Endpoint pattern
app.post('/api/endpoint', async (req: Request, res: Response) => {
  try {
    const result = await Service.process(req.body);
    res.json(result);
  } catch (error) {
    logger.error('Error:', error);
    res.status(500).json({ error: 'Internal server error' });
  }
});
```

### React + TypeScript
```typescript
// Component pattern
interface Props {
  data: DataType;
  onAction: (value: string) => void;
}

export const Component: React.FC<Props> = ({ data, onAction }) => {
  const [state, setState] = useState<StateType>();
  
  return <div>{/* JSX */}</div>;
};
```

## 🚀 Benefits for Your Team

- **Consistent code style** across all services
- **Faster onboarding** for new developers
- **Better code quality** with automated guidelines
- **Unified development practices** across Chessverse
- **AI as mentor** instead of just code generator

## 📞 Support

If you need help customizing rules for your stack:
1. Check existing examples in this repository
2. Ask in #development channel
3. Create issue with your specific technology stack
