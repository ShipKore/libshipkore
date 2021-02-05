class BaseService(object):
    def __init__(self, *args, **kwargs):
        # super().__init__(*args, **kwargs)
        self.raw_data = kwargs.get('raw_data')
        self.data = kwargs.get('data')
        self.args = args
        self.kwargs = kwargs

    '''
    This method will perform authorization for _fetch
    '''

    def _auth(self):
        pass

    '''
    This method will populate self.raw_data
    '''

    def _fetch(self):
        raise NotImplementedError

    '''
    This method will convert self.raw_data to self.data
    '''

    def _transform(self):
        raise NotImplementedError

    '''
    This method will convert save self.data to firebase 
    '''

    def _save(self):
        raise NotImplementedError

    def run(self):
        self._auth()
        self._fetch()
        self._transform()
        self._save()
        return self.data

    def get(self):
        raise NotImplementedError
