"""Page-specific project context; changing publishing never switches exploration."""
from workflow import project,scoped


def workspace_project(data,workspace,pid=None):
    if workspace not in {'exploration','publishing'}:raise ValueError('工作空间无效')
    pid=pid or data.get('active_publishing_project_id' if workspace=='publishing' else 'active_project_id')
    if not pid:return None
    row=project(data,pid)
    if row.get('workspace','exploration')!=workspace:raise ValueError('项目不属于这个工作空间')
    return row


class ProjectFiles:
    def __init__(self,files,pid=None,workspace='publishing'):
        self.files=files;self.path=files.path;self.workspace=workspace
        row=workspace_project(files.load(),workspace,pid)
        if not row:raise ValueError('请先创建发布项目')
        self.pid=row['id']
    def load(self):
        data=self.files.load();workspace_project(data,self.workspace,self.pid)
        data['active_project_id']=self.pid
        return data
    def change(self,action):
        def apply(data):
            workspace_project(data,self.workspace,self.pid)
            previous=data['active_project_id'];data['active_project_id']=self.pid
            try:return action(data)
            finally:data['active_project_id']=previous
        return self.files.change(apply)
