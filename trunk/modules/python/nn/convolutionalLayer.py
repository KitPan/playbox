from nn.layer import Layer
import numpy as np
from theano.tensor import tanh, switch
from theano import shared, config, function

class ConvolutionalLayer(Layer) :
    '''This class describes a Convolutional Neural Layer which specifies
       a series of kernels and subsample.

       layerID           : unique name identifier for this layer
       input             : the input buffer for this layer
       inputSize         : (batch size, channels, rows, columns)
       kernelSize        : (number of kernels, channels, rows, columns)
       downsampleFactor  : (rowFactor, columnFactor)
       learningRate      : learning rate for all neurons
       momentumRate      : rate of momentum for all neurons
                           NOTE: momentum allows for higher learning rates
       dropout           : rate of retention in a given neuron during training
                           NOTE: input layers should be around .8 or .9
                                 hidden layers should be around .5 or .6
                                 output layers should always be 1.
       initialWeights    : weights to initialize the network
                           None generates random weights for the layer
       initialThresholds : thresholds to initialize the network
                           None generates random thresholds for the layer
       activation        : the sigmoid function to use for activation
                           this must be a function with a derivative form
       randomNumGen      : generator for the initial weight values - 
                           type is numpy.random.RandomState
    '''
    def __init__ (self, layerID, input, inputSize, kernelSize, 
                  downsampleFactor, learningRate=0.001, momentumRate=0.9,
                  dropout=None, initialWeights=None, initialThresholds=None,
                  activation=tanh, randomNumGen=None) :
        Layer.__init__(self, layerID, learningRate, momentumRate, dropout)

        # TODO: this check is likely unnecessary
        if inputSize[2] == kernelSize[2] or inputSize[3] == kernelSize[3] :
            raise ValueError('ConvolutionalLayer Error: ' +
                             'inputSize cannot equal kernelSize')
        if inputSize[1] != kernelSize[1] :
            raise ValueError('ConvolutionalLayer Error: ' +
                             'Number of Channels must match in ' +
                             'inputSize and kernelSize')
        from theano.tensor.nnet.conv import conv2d
        from theano.tensor.signal.downsample import max_pool_2d

        # theano variables don't actually preserve buffer sizing
        self.input = input if isinstance(input, tuple) else (input, input)

        self._inputSize = inputSize
        self._kernelSize = kernelSize
        self._downsampleFactor = downsampleFactor

        # setup initial values for the weights -- if necessary
        if initialWeights is None :
            # create a rng if its needed
            if randomNumGen is None :
                from numpy.random import RandomState
                from time import time
                randomNumGen = RandomState(int(time()))

            # this creates optimal initial weights by randomizing them
            # to an appropriate range around zero, which leads to better
            # convergence.
            downRate = np.prod(self._downsampleFactor)
            fanIn = np.prod(self._kernelSize[1:])
            fanOut = self._kernelSize[0] * \
                     np.prod(self._kernelSize[2:]) / downRate
            scaleFactor = np.sqrt(6. / (fanIn + fanOut))
            initialWeights = np.asarray(randomNumGen.uniform(
                    low=-scaleFactor, high=scaleFactor, size=self._kernelSize),
                    dtype=config.floatX)
        self._weights = shared(value=initialWeights, borrow=True)

        # setup initial values for the thresholds -- if necessary
        if initialThresholds is None :
            initialThresholds = np.zeros((self._kernelSize[0],),
                                         dtype=config.floatX)
        self._thresholds = shared(value=initialThresholds, borrow=True)

        def findLogits(input, weights, 
                       inputSize, kernelSize, downsampleFactor, thresholds) :
            # create a function to perform the convolution
            convolve = conv2d(input, weights, inputSize, kernelSize)

            # create a function to perform the max pooling
            pooling = max_pool_2d(convolve, downsampleFactor, True)

            # the output buffer is now connected to a sequence of operations
            return pooling + thresholds.dimshuffle('x', 0, 'x', 'x')

        outClass = findLogits(self.input[0], self._weights,
                              self._inputSize, self._kernelSize,
                              self._downsampleFactor, self._thresholds)
        outTrain = findLogits(self.input[1], self._weights,
                              self._inputSize, self._kernelSize,
                              self._downsampleFactor, self._thresholds)

        # determine dropout if requested
        if self._dropout is not None :
            # here there are two possible paths --
            # outClass : path of execution intended for classification. Here
            #            all neurons are present and weights must be scaled by
            #            the dropout factor. This ensures resultant 
            #            probabilities fall within intended bounds when all
            #            neurons are present.
            # outTrain : path of execution for training with dropout. Here each
            #            neuron's output goes through a Bernoulli Trial. This
            #            retains a neuron with the probability specified by the
            #            dropout factor.
            outClass = outClass / self._dropout
            outTrain = switch(self._randStream.binomial(
                size=self.getOutputSize()[1:], p=self._dropout), outTrain, 0)

        # activate the layer --
        # output is a tuple to represent two possible paths through the
        # computation graph. 
        self.output = (outClass, outTrain) if activation is None else \
                      (activation(outClass), activation(outTrain))

        # we can call this method to activate the layer
        self.activate = function([self.input[0]], self.output[0])

    def getWeights(self) :
        '''This allows the network backprop all layers efficiently.'''
        return [self._weights, self._thresholds]
    def getInputSize (self) :
        '''The initial input size provided at construction. This is sized
           (batch size, channels, rows, columns)'''
        return self._inputSize
    def getKernelSize (self) :
        '''The initial kernel size provided at construction. This is sized
           (number of kernels, channels, rows, columns)'''
        return self._kernelSize
    def getFeatureSize (self) :
        '''This is the post convolution size of the output.
           (batch size, number of kernels, rows, columns)'''
        return (self._inputSize[0], 
                self._kernelSize[0],
                self._inputSize[2] - self._kernelSize[2] + 1,
                self._inputSize[3] - self._kernelSize[3] + 1)
    def getOutputSize (self) :
        '''This is the post downsample size of the output.
           (batch size, number of kernels, rows, columns)'''
        fShape = self.getFeatureSize()
        return (fShape[0], fShape[1],
                int(fShape[2] / self._downsampleFactor[0]),
                int(fShape[3] / self._downsampleFactor[1]))

    # DEBUG: For Debugging purposes only 
    def writeWeights(self, ii) :
        from dataset.debugger import saveTiledImage
        saveTiledImage(image=self._weights.get_value(borrow=True),
                       path=self.layerID + '_cae_filters_' + str(ii) + '.png',
                       imageShape=(self._kernelSize[2], self._kernelSize[3]),
                       spacing=1,
                       interleave=True)
