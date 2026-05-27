declare interface FileSystemHandlePermissionDescriptor {
  mode?: 'read' | 'readwrite'
}

declare interface FileSystemHandle {
  readonly kind: 'file' | 'directory'
  readonly name: string
  queryPermission?(
    descriptor?: FileSystemHandlePermissionDescriptor,
  ): Promise<PermissionState>
  requestPermission?(
    descriptor?: FileSystemHandlePermissionDescriptor,
  ): Promise<PermissionState>
}

declare interface FileSystemFileHandle extends FileSystemHandle {
  readonly kind: 'file'
  getFile(): Promise<File>
  createWritable(
    options?: {
      keepExistingData?: boolean
    },
  ): Promise<FileSystemWritableFileStream>
}

declare interface FileSystemDirectoryHandle extends FileSystemHandle {
  readonly kind: 'directory'
  getFileHandle(
    name: string,
    options?: {
      create?: boolean
    },
  ): Promise<FileSystemFileHandle>
}

declare interface FileSystemWritableFileStream extends WritableStream {
  write(data: BufferSource | Blob | string): Promise<void>
  close(): Promise<void>
}

declare interface Window {
  showDirectoryPicker?: (
    options?: unknown,
  ) => Promise<FileSystemDirectoryHandle>
  showSaveFilePicker?: (
    options?: unknown,
  ) => Promise<FileSystemFileHandle>
}
