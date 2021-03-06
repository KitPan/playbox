import theano.tensor as t
import theano
from nn.net import Network
from ae.encoder import AutoEncoder
import numpy as np

class StackedAENetwork (Network) :
    '''The StackedAENetwork object allows autoencoders to be stacked such that
       the output of one autoencoder becomes the input to another. It creates
       the necessary connections to train the AE in a greedy layerwise manner. 
       The resulting trained AEs can be used to initialize a nn.TrainerNetwork.

       train : theano.shared dataset used for network training in format --
               (numBatches, batchSize, numChannels, rows, cols)
       log   : Logger to use
    '''
    def __init__ (self, train, log=None) :
        Network.__init__ (self, log)
        self._indexVar = t.lscalar('index')
        self._trainData = train
        self._numTrainBatches = self._trainData.get_value(borrow=True).shape[0]
        self._greedyTrainer = []

    def __buildAE(self, encoder) :
        out, updates = encoder.getUpdates()
        self._greedyTrainer.append(
            theano.function([self._indexVar], out, updates=updates,
                            givens={self.getNetworkInput()[1] : 
                                    self._trainData[self._indexVar]}))

    def __getstate__(self) :
        '''Save network pickle'''
        dict = Network.__getstate__(self)
        # remove the functions -- they will be rebuilt JIT
        if '_indexVar' in dict : del dict['_indexVar']
        if '_trainData' in dict : del dict['_trainData']
        if '_numTrainBatches' in dict : del dict['_numTrainBatches']
        if '_greedyTrainer' in dict : del dict['_greedyTrainer']
        return dict

    def __setstate__(self, dict) :
        '''Load network pickle'''
        # remove any current functions from the object so we force the
        # theano functions to be rebuilt with the new buffers
        if hasattr(self, '_greedyTrainer') : delattr(self, '_greedyTrainer')
        self._greedyTrainer = []
        Network.__setstate__(self, dict)
        # rebuild the network
        for encoder in self._layers :
            self.__buildAE(encoder)

    def addLayer(self, encoder) :
        '''Add an autoencoder to the network. It is the responsibility of the 
           user to connect the current network's output as the input to the 
           next layer.
           This utility will additionally create a greedy layerwise trainer.
        '''
        if not isinstance(encoder, AutoEncoder) :
            raise TypeError('addLayer is expecting a AutoEncoder object.')
        self._startProfile('Adding a Encoder to the network', 'debug')

        # add it to our layer list
        self._layers.append(encoder)

        # all layers start with the input original input, however are updated
        # in a layerwise manner. --
        # NOTE: this uses theano.shared variables for optimized GPU execution
        self.__buildAE(encoder)
        self._endProfile()

    def train(self, layerIndex, index) :
        '''Train the network against the pre-loaded inputs. This accepts
           a batch index into the pre-compiled input set.
           layerIndex : specify which layer to train
           index      : specify a pre-compiled mini-batch index
           inputs     : DEBUGGING Specify a numpy tensor mini-batch
        '''
        self._startProfile('Training Batch [' + str(index) +
                           '/' + str(self._numTrainBatches) + ']', 'debug')
        if not isinstance(index, int) :
            raise Exception('Variable index must be an integer value')
        if index >= self._numTrainBatches :
            raise Exception('Variable index out of range for numBatches')

        # train the input --
        # the user decides if this is online or batch training
        ret = self._greedyTrainer[layerIndex](index)

        self._endProfile()
        return ret

    def trainEpoch(self, layerIndex, globalEpoch, numEpochs=1) :
        '''Train the network against the pre-loaded inputs for a user-specified
           number of epochs.

           layerIndex  : index of the layer to train
           globalEpoch : total number of epochs the network has previously 
                         trained
           numEpochs   : number of epochs to train this round before stopping
        '''
        globCost = []
        for localEpoch in range(numEpochs) :
            layerEpochStr = 'Layer[' + str(layerIndex) + '] Epoch[' + \
                            str(globalEpoch + localEpoch) + ']'
            self._startProfile('Running ' + layerEpochStr, 'info')
            locCost = []
            for ii in range(self._numTrainBatches) :
                locCost.append(self.train(layerIndex, ii))

            locCost = np.mean(locCost, axis=0)
            self._startProfile(layerEpochStr + ' Cost: ' + \
                               str(locCost[0]) + ' - Jacob: ' + \
                               str(locCost[1]), 'info')
            globCost.append(locCost)

            self._endProfile()
            self._endProfile()

            #self.writeWeights(layerIndex, globalEpoch + localEpoch)
        return globalEpoch + numEpochs, globCost

    def trainGreedyLayerwise(self, numEpochs=1) :
        '''Train the entire network against the pre-loaded inputs for a 
           user-specified number of epochs. This trains all layers for the
           specified number of epochs before moving to the next layer.

           numEpochs   : number of epochs to train this round before stopping
        '''
        for layerIndex in range(self.getNumLayers()) :
            self.trainEpoch(layerIndex, 0, numEpochs)

    # TODO: these should both be removed!
    def getLayer(self, layerIndex) :
        return self._layers[layerIndex]
    def writeWeights(self, layerIndex, epoch) :
        self._layers[layerIndex].writeWeights(epoch)


if __name__ == '__main__' :
    import argparse, logging
    from dataset.reader import ingestImagery, pickleDataset
    from dataset.shared import splitToShared
    from contiguousAE import ContractiveAutoEncoder

    parser = argparse.ArgumentParser()
    parser.add_argument('--log', dest='logfile', type=str, default=None,
                        help='Specify log output file.')
    parser.add_argument('--level', dest='level', default='info', type=str, 
                        help='Log Level.')
    parser.add_argument('--contraction', dest='contraction', default=0.1, 
                        type=float, help='Rate of contraction.')
    parser.add_argument('--learn', dest='learn', type=float, default=0.01,
                        help='Rate of learning on AutoEncoder.')
    parser.add_argument('--neuron', dest='neuron', type=int, default=100,
                        help='Number of Neurons in Hidden Layer.')
    parser.add_argument('data', help='Directory or pkl.gz file for the ' +
                                     'training and test sets')
    options = parser.parse_args()

    # setup the logger
    log = logging.getLogger('CAE: ' + options.data)
    log.setLevel(options.level.upper())
    formatter = logging.Formatter('%(levelname)s - %(message)s')
    stream = logging.StreamHandler()
    stream.setLevel(options.level.upper())
    stream.setFormatter(formatter)
    log.addHandler(stream)
    if options.logfile is not None :
        logFile = logging.FileHandler(options.logfile)
        logFile.setLevel(options.level.upper())
        logFile.setFormatter(formatter)
        log.addHandler(logFile)

    # NOTE: The pickleDataset will silently use previously created pickles if
    #       one exists (for efficiency). So watch out for stale pickles!
    train, test, labels = ingestImagery(pickleDataset(
            options.data, batchSize=100, 
            holdoutPercentage=0, log=log), shared=False, log=log)
    vectorized = (train[0].shape[0], train[0].shape[1], 
                  train[0].shape[3] * train[0].shape[4])
    train = (np.reshape(train[0], vectorized), train[1])

    network = StackedAENetwork(splitToShared(train, borrow=True), log)
    input = t.fmatrix('input')
    network.addLayer(ContractiveAutoEncoder(
        'cae', input, (vectorized[1], vectorized[2]),
        options.neuron, options.learn, options.contraction))

    globalEpoch = 0
    for ii in range(100) :
        globalEpoch, globalCost = network.trainEpoch(0, globalEpoch)
    network.writeWeights(0)
    del network
